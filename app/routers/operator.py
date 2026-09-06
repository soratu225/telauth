"""
app/routers/operator.py - 運営者向けREST API

運営者向け (X-API-Key 必須):
  POST   /api/v1/code                           画面に表示する認証コードを発行する
  GET    /api/v1/auth-status                    電話での認証が完了したか確認する
  POST   /api/v1/verify                         OTPを検証する
  GET    /api/v1/phones                         登録済み電話番号一覧
  GET    /api/v1/logs                           着信・認証ログ一覧
  GET    /api/v1/phones/{phone_number}/secret   TOTPシークレット取得
  DELETE /api/v1/phones/{phone_number}          電話番号のシークレットを削除

Asterisk 内部呼び出し (INTERNAL_TOKEN 設定時は X-Internal-Token 必須):
  GET    /api/v1/inbound                        着信を記録する
  GET    /api/v1/inbound-verify                 電話で入力されたコードを照合する
  GET    /api/v1/call-complete                  通話終了 (秒数) を記録する
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import CallLog, PhoneSecret
from app.otp import (
    decrypt_secret,
    encrypt_secret,
    generate_otp,
    generate_secret,
    get_provisioning_uri,
    verify_otp,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["operator"])

# ---------------------------------------------------------------------------
# API Key認証
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(key: str = Security(api_key_header)) -> str:
    if key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効なAPIキーです",
        )
    return key


async def verify_internal_token(
    x_internal_token: str | None = Header(default=None),
) -> None:
    """Asterisk からの内部呼び出し用。INTERNAL_TOKEN が設定されているときだけ検査する。"""
    if settings.internal_token and x_internal_token != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無効な内部トークンです",
        )


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

async def get_or_create_secret(
    phone_number: str, db: AsyncSession
) -> PhoneSecret:
    """電話番号のPhoneSecretを取得。存在しなければ新規作成する。"""
    result = await db.execute(
        select(PhoneSecret).where(PhoneSecret.phone_number == phone_number)
    )
    record = result.scalar_one_or_none()
    if record is None:
        plain = generate_secret()
        record = PhoneSecret(
            phone_number=phone_number,
            encrypted_secret=encrypt_secret(plain),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        logger.info(f"新規シークレット登録: {phone_number}")
    return record


async def check_rate_limit(phone_number: str, db: AsyncSession) -> None:
    """レート制限チェック。制限内であればHTTPExceptionを送出する。"""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.call_rate_limit_seconds
    )
    result = await db.execute(
        select(CallLog)
        .where(CallLog.phone_number == phone_number)
        .where(CallLog.called_at >= cutoff)
        .order_by(CallLog.called_at.desc())
        .limit(1)
    )
    recent = result.scalar_one_or_none()
    if recent:
        # SQLiteはtzinfo付きで保存しないことがあるため、UTC前提でaware化する
        called_at = recent.called_at
        if called_at.tzinfo is None:
            called_at = called_at.replace(tzinfo=timezone.utc)
        wait_sec = int(
            settings.call_rate_limit_seconds
            - (datetime.now(timezone.utc) - called_at).total_seconds()
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"発信制限中です。{wait_sec}秒後に再試行してください。",
        )


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------

class CodeRequest(BaseModel):
    phone_number: str = Field(
        ..., examples=["09012341234"], description="利用者が発信する電話番号"
    )


class CodeResponse(BaseModel):
    phone_number: str
    code: str = Field(..., description="画面に表示して電話で入力してもらう認証コード")
    expires_in_seconds: int = Field(..., description="このコードが切り替わるまでの秒数")


class AuthStatusResponse(BaseModel):
    phone_number: str
    verified: bool
    verified_at: datetime | None


class VerifyRequest(BaseModel):
    phone_number: str = Field(..., examples=["09012341234"])
    code: str = Field(..., min_length=6, max_length=6, examples=["123456"])


class VerifyResponse(BaseModel):
    valid: bool


class PhoneInfo(BaseModel):
    phone_number: str
    created_at: datetime
    last_called_at: datetime | None


class SecretInfo(BaseModel):
    phone_number: str
    secret: str
    provisioning_uri: str


class CallLogInfo(BaseModel):
    id: int
    phone_number: str
    status: str
    otp_code: str | None
    duration_seconds: int | None
    called_at: datetime


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------

@router.post(
    "/code",
    response_model=CodeResponse,
    summary="画面に表示する認証コードを発行する",
    dependencies=[Depends(verify_api_key)],
)
async def issue_code(body: CodeRequest, db: AsyncSession = Depends(get_db)):
    """
    利用者の電話番号に対する現在の認証コードを返します。
    運営者アプリはこのコードを画面に表示し、利用者はその番号から電話してコードを入力します。
    コードは電話番号ごとの TOTP なので、他人のコードを入力しても照合に失敗します。
    """
    record = await get_or_create_secret(body.phone_number, db)
    plain = decrypt_secret(record.encrypted_secret)
    interval = settings.otp_interval_seconds
    expires_in = interval - (int(datetime.now(timezone.utc).timestamp()) % interval)
    return CodeResponse(
        phone_number=body.phone_number,
        code=generate_otp(plain),
        expires_in_seconds=expires_in,
    )


def _as_utc(dt: datetime) -> datetime:
    """SQLite は tz を保存しないので UTC 前提で aware 化する。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get(
    "/auth-status",
    response_model=AuthStatusResponse,
    summary="電話での認証が完了したか確認する",
    dependencies=[Depends(verify_api_key)],
)
async def auth_status(
    phone_number: str,
    within_seconds: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    指定した電話番号で、within_seconds 秒以内（既定はコードの有効期間）に
    電話でのコード照合が成功していれば verified=true を返します。運営者アプリがポーリングします。
    """
    window = within_seconds if within_seconds is not None else settings.otp_interval_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window)
    result = await db.execute(
        select(CallLog)
        .where(CallLog.phone_number == phone_number)
        .where(CallLog.status == "verified")
        .where(CallLog.called_at >= cutoff)
        .order_by(CallLog.called_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return AuthStatusResponse(
        phone_number=phone_number,
        verified=row is not None,
        verified_at=_as_utc(row.called_at) if row else None,
    )


@router.get(
    "/inbound",
    summary="着信記録 (Asteriskから呼び出し)",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
)
async def handle_inbound(phone_number: str, db: AsyncSession = Depends(get_db)):
    """
    電話認証が選ばれたときにダイヤルプランから呼び出される。
    着信ログ（電話番号・時刻）を保存し、シークレットが無ければ作成する。
    """
    if not phone_number or phone_number.lower() in ["anonymous", "unknown"]:
        return {"status": "error", "message": "no caller id"}

    record = await get_or_create_secret(phone_number, db)
    log_entry = CallLog(
        phone_number=phone_number,
        call_id=None,
        status="inbound_answered",
        otp_code=None,
        duration_seconds=None,  # 通話終了時に /call-complete で更新
    )
    db.add(log_entry)
    record.last_called_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(log_entry)
    logger.info(f"着信: {phone_number} (log_id={log_entry.id})")
    return {"status": "ok", "log_id": log_entry.id}


@router.get(
    "/inbound-verify",
    summary="電話で入力された認証コードの照合 (Asteriskから呼び出し)",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
)
async def inbound_verify(
    phone_number: str,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    発信者番号 (phone_number) のシークレットで code を照合する。
    一致すれば 200、不一致・未登録・失敗回数超過なら 401 を返す
    (ダイヤルプランは curl の終了コードで成否を判定する)。
    結果は CallLog に verified / verify_failed として記録する。
    """
    code = code.strip()
    result = await db.execute(
        select(PhoneSecret).where(PhoneSecret.phone_number == phone_number)
    )
    record = result.scalar_one_or_none()

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.otp_interval_seconds)
    failures_result = await db.execute(
        select(CallLog)
        .where(CallLog.phone_number == phone_number)
        .where(CallLog.status == "verify_failed")
        .where(CallLog.called_at >= cutoff)
    )
    failures = len(failures_result.scalars().all())
    locked = failures >= settings.verify_max_failures

    valid = False
    if record is not None and not locked:
        valid = verify_otp(decrypt_secret(record.encrypted_secret), code)

    db.add(
        CallLog(
            phone_number=phone_number,
            status="verified" if valid else "verify_failed",
            otp_code=code[:10],
        )
    )
    await db.commit()

    if valid:
        logger.info(f"コード照合 成功: {phone_number}")
        return {"valid": True}

    reason = "locked" if locked else ("unregistered" if record is None else "mismatch")
    logger.warning(f"コード照合 失敗: {phone_number} reason={reason} failures={failures + 1}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"valid": False, "reason": reason},
    )


@router.get(
    "/call-complete",
    summary="通話終了通知 (Asteriskから呼び出し)",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
)
async def call_complete(
    phone_number: str,
    duration: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Asteriskのダイヤルプランから通話終了時に呼び出される。
    最新の着信ログに通話秒数を記録する。

    duration はダイヤルプランの変数展開で空文字になることがあるため、
    int で受けず自前でパースする（空/不正値は 0 秒扱い）。
    """
    from sqlalchemy import desc

    try:
        duration_sec = max(0, int(float(duration))) if duration else 0
    except (TypeError, ValueError):
        logger.warning(f"通話秒数を解釈できません: {duration!r} ({phone_number})")
        duration_sec = 0

    result = await db.execute(
        select(CallLog)
        .where(CallLog.phone_number == phone_number)
        .where(CallLog.status == "inbound_answered")
        .order_by(desc(CallLog.called_at))
        .limit(1)
    )
    log_entry = result.scalar_one_or_none()
    if log_entry:
        log_entry.duration_seconds = duration_sec
        log_entry.status = "completed"
        await db.commit()
        logger.info(f"通話完了ログ更新: {phone_number} duration={duration_sec}s")

    return {"status": "ok"}

@router.post(
    "/verify",
    response_model=VerifyResponse,
    summary="OTPコードを検証する",
    dependencies=[Depends(verify_api_key)],
)
async def verify(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """指定した電話番号のOTPコードを検証します。"""
    result = await db.execute(
        select(PhoneSecret).where(PhoneSecret.phone_number == body.phone_number)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定した電話番号は登録されていません",
        )

    plain = decrypt_secret(record.encrypted_secret)
    is_valid = verify_otp(plain, body.code)
    return VerifyResponse(valid=is_valid)


@router.get(
    "/phones",
    response_model=list[PhoneInfo],
    summary="登録済み電話番号一覧を取得する",
    dependencies=[Depends(verify_api_key)],
)
async def list_phones(db: AsyncSession = Depends(get_db)):
    """DBに登録された全電話番号とメタ情報を返します。"""
    result = await db.execute(select(PhoneSecret).order_by(PhoneSecret.created_at.desc()))
    records = result.scalars().all()
    return [
        PhoneInfo(
            phone_number=r.phone_number,
            created_at=r.created_at,
            last_called_at=r.last_called_at,
        )
        for r in records
    ]


@router.get(
    "/logs",
    response_model=list[CallLogInfo],
    summary="着信・認証ログ一覧を取得する（15年保管）",
    dependencies=[Depends(verify_api_key)],
)
async def list_logs(
    phone_number: str | None = None,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
):
    """
    着信・認証ログを返します。phone_numberで絞り込み可能。
    status: inbound_answered (着信) / completed (通話終了) / verified (照合成功) / verify_failed (照合失敗)
    ログはDBに永続保管されます（自動削除なし）。
    """
    from sqlalchemy import desc
    query = select(CallLog).order_by(desc(CallLog.called_at)).limit(limit)
    if phone_number:
        query = query.where(CallLog.phone_number == phone_number)
    result = await db.execute(query)
    records = result.scalars().all()
    return [
        CallLogInfo(
            id=r.id,
            phone_number=r.phone_number,
            status=r.status,
            otp_code=r.otp_code,
            duration_seconds=r.duration_seconds,
            called_at=r.called_at,
        )
        for r in records
    ]


@router.get(
    "/phones/{phone_number}/secret",
    response_model=SecretInfo,
    summary="TOTPシークレットを取得する（アプリ連携用）",
    dependencies=[Depends(verify_api_key)],
)
async def get_phone_secret(
    phone_number: str,
    db: AsyncSession = Depends(get_db),
):
    """
    電話番号のTOTPシークレットとプロビジョニングURIを返します。
    Google Authenticatorなどのアプリとの連携に使用できます。
    ※ interval=900のためGoogle Authenticatorアプリとは互換しません。
    """
    result = await db.execute(
        select(PhoneSecret).where(PhoneSecret.phone_number == phone_number)
    )
    record = result.scalar_one_or_none()
    if record is None:
        # 自動登録して返す
        record = await get_or_create_secret(phone_number, db)

    plain = decrypt_secret(record.encrypted_secret)
    return SecretInfo(
        phone_number=phone_number,
        secret=plain,
        provisioning_uri=get_provisioning_uri(plain, phone_number),
    )


@router.delete(
    "/phones/{phone_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="電話番号のシークレットを削除する",
    dependencies=[Depends(verify_api_key)],
)
async def delete_phone(
    phone_number: str,
    db: AsyncSession = Depends(get_db),
):
    """指定した電話番号のTOTPシークレットとログをDBから削除します。"""
    result = await db.execute(
        select(PhoneSecret).where(PhoneSecret.phone_number == phone_number)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定した電話番号は登録されていません",
        )
    await db.execute(
        delete(CallLog).where(CallLog.phone_number == phone_number)
    )
    await db.delete(record)
    await db.commit()
