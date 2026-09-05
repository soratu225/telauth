"""
app/routers/operator.py - 運営者向けREST API

エンドポイント一覧:
  POST   /api/v1/call-otp                       発信してOTPを読み上げる
  POST   /api/v1/verify                         OTPを検証する
  GET    /api/v1/phones                         登録済み電話番号一覧
  GET    /api/v1/phones/{phone_number}/secret   TOTPシークレット取得
  DELETE /api/v1/phones/{phone_number}          電話番号のシークレットを削除
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Security, status
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

class CallOtpRequest(BaseModel):
    phone_number: str = Field(..., examples=["09012341234"], description="発信先電話番号")


class CallOtpResponse(BaseModel):
    phone_number: str
    call_id: str | None
    message: str


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

@router.get(
    "/inbound",
    summary="インバウンド着信処理 (Asteriskから呼び出し)",
    include_in_schema=False,
)
async def handle_inbound(phone_number: str, db: AsyncSession = Depends(get_db)):
    """
    着信時にAsteriskのダイヤルプランから呼び出される。
    OTPと音声を生成し、着信ログ（電話番号・OTP・時間）をDBに保存する。
    """
    if not phone_number or phone_number.lower() in ["anonymous", "unknown"]:
        return {"status": "error", "message": "no caller id"}

    record = await get_or_create_secret(phone_number, db)
    plain_secret = decrypt_secret(record.encrypted_secret)
    otp_code = generate_otp(plain_secret)

    logger.info(f"着信処理 - OTP生成: {phone_number} -> {otp_code}")

    # 着信ログをDBに保存（電話番号・OTP・時間を記録、15年保管）
    log_entry = CallLog(
        phone_number=phone_number,
        call_id=None,
        status="inbound_answered",
        otp_code=otp_code,
        duration_seconds=None,  # 通話終了時に /call-complete で更新
    )
    db.add(log_entry)

    # last_called_at を更新
    record.last_called_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(log_entry)

    from app.tts import generate_otp_prompts
    files = generate_otp_prompts(otp_code, filename_base=f"otp_{phone_number}")

    return {"status": "ok", "files": files, "log_id": log_entry.id}


@router.get(
    "/call-complete",
    summary="通話終了通知 (Asteriskから呼び出し)",
    include_in_schema=False,
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
    summary="着信ログ一覧を取得する（15年保管）",
    dependencies=[Depends(verify_api_key)],
)
async def list_logs(
    phone_number: str | None = None,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
):
    """
    着信ログを返します。phone_numberで絞り込み可能。
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
