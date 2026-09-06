"""
app/extension_calls.py - 内線呼び出しサービス

流れ:
  start_call : 内線番号と受付時間を確認し、担当者全員の Discord DM に「出る / 拒否」付きの通知を送る
  accept     : 最初に「出る」を押した人が担当。担当者用の SIP アカウント (web1..webN) を割り当て、
               その人の DM だけに通話ページの URL を出す。ページが Asterisk に WebSocket で登録すると
               ダイヤルプランがそのアカウントへ Dial して発信者とつなぐ
  reject     : 全員が拒否したら rejected
  timeout    : 待ち時間 (既定 3 分) を過ぎたら timeout
  ended      : 通話終了
状態は ExtensionCall.status: ringing / accepted / rejected / timeout / ended / error
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ExtensionCall
from app.notify import CallCard, CardButton, NotificationRef, get_notifier

logger = logging.getLogger(__name__)
settings = get_settings()

# Discord Bot など、リクエスト外から DB を使うときのセッション工場 (テストで差し替える)
session_factory = AsyncSessionLocal

COLOR_RINGING = 0xF39C12
COLOR_OK = 0x2ECC71
COLOR_NG = 0xE74C3C
COLOR_GRAY = 0x95A5A6


# ---------------------------------------------------------------------------
# 内線表 / 受付時間 / 表示用ヘルパー
# ---------------------------------------------------------------------------

def load_extensions() -> dict[str, dict]:
    """extensions.json を読む。{"101": {"label": "...", "discord_user_ids": [...]}}"""
    path = Path(settings.extensions_file)
    if not path.exists():
        logger.warning(f"内線表が見つかりません: {path}")
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict] = {}
    for ext, cfg in data.items():
        if isinstance(cfg, list):
            cfg = {"discord_user_ids": cfg}
        ids = [str(u) for u in cfg.get("discord_user_ids", [])]
        result[str(ext)] = {"label": cfg.get("label") or f"内線{ext}", "discord_user_ids": ids}
    return result


def is_open(now: datetime | None = None) -> bool:
    """受付時間内か (EXTENSION_HOURS_START <= 時 < EXTENSION_HOURS_END、EXTENSION_TIMEZONE 基準)。"""
    tz = ZoneInfo(settings.extension_timezone)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    return settings.extension_hours_start <= local.hour < settings.extension_hours_end


def format_phone(number: str) -> str:
    """表示用にハイフンを入れる。例: 08012345678 -> 080-1234-5678
    特殊コマンド使用の非通知発信者は専用ラベルで表示する。
    """
    if number == "0000777000":
        return "非通知（特殊コマンド使用）"
    digits = number
    if digits.startswith("+81"):
        digits = "0" + digits[3:]
    if not digits.isdigit():
        return number
    if digits.startswith(("0120", "0800")) and len(digits) == 10:
        return f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        if digits.startswith(("03", "06")):
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return number


_BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?$")


def public_base_url() -> str:
    """PUBLIC_BASE_URL が正しい URL のときだけ返す。プレースホルダーや全角文字が入っていれば空 (未設定扱い)。"""
    base = settings.public_base_url.strip().rstrip("/")
    if not base:
        return ""
    if not _BASE_URL_RE.match(base):
        logger.warning(f"PUBLIC_BASE_URL が URL として不正なので無視します: {base!r}")
        return ""
    return base


def join_url(call: ExtensionCall) -> str:
    return f"{public_base_url()}/ext/join/{call.id}?t={call.join_secret}"


# ---------------------------------------------------------------------------
# 担当者用 SIP アカウント (WebRTC) のプール
# ---------------------------------------------------------------------------

def webrtc_secret() -> str:
    return settings.webrtc_secret or settings.internal_token or "changeme"


def slot_password(slot: str) -> str:
    """entrypoint.sh と同じ計算: sha256("<secret>:<slot>") の先頭 32 文字。"""
    return hashlib.sha256(f"{webrtc_secret()}:{slot}".encode()).hexdigest()[:32]


def all_slots() -> list[str]:
    return [f"web{i}" for i in range(1, settings.webrtc_slots + 1)]


async def pick_free_slot(db: AsyncSession) -> str | None:
    """通話中 (accepted) の呼び出しが使っていないスロットを返す。古い取りこぼしは 2 時間で解放。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    result = await db.execute(
        select(ExtensionCall.webrtc_slot)
        .where(ExtensionCall.status == "accepted")
        .where(ExtensionCall.accepted_at >= cutoff)
    )
    in_use = {row[0] for row in result.all() if row[0]}
    for slot in all_slots():
        if slot not in in_use:
            return slot
    return None


def _label(call: ExtensionCall) -> str:
    return load_extensions().get(call.extension, {}).get("label", f"内線{call.extension}")


def _refs(call: ExtensionCall) -> list[NotificationRef]:
    return [NotificationRef.from_dict(d) for d in json.loads(call.notifications or "[]")]


# ---------------------------------------------------------------------------
# DM の内容 (状態と見る人によって変わる)
# ---------------------------------------------------------------------------

def card_for(call: ExtensionCall, user_id: str) -> CallCard:
    title = f"📞 {format_phone(call.phone_number)} からお電話です！"
    head = f"{_label(call)}（内線 {call.extension}）への着信です。"
    rejected = set(json.loads(call.rejected_by or "[]"))

    if call.status == "ringing":
        if user_id in rejected:
            return CallCard(title, f"{head}\n拒否しました。他の担当者の応答を待っています。", COLOR_GRAY)
        return CallCard(
            title,
            f"{head}\n出られる方は「出る」を押してください。",
            COLOR_RINGING,
            [
                CardButton("出る", "success", custom_id=f"extcall:{call.id}:accept"),
                CardButton("拒否", "danger", custom_id=f"extcall:{call.id}:reject"),
            ],
        )
    if call.status == "accepted":
        if user_id == call.accepted_by:
            url = join_url(call)
            if public_base_url():
                return CallCard(
                    title,
                    f"{head}\nあなたが対応しています。下のボタンから対応してください！",
                    COLOR_OK,
                    [CardButton("通話に参加", "link", url=url)],
                )
            return CallCard(
                title,
                f"{head}\n✅ あなたが対応中です。参加ページ: `{url}`\n（PUBLIC_BASE_URL が未設定のためリンクにできません）",
                COLOR_OK,
            )
        return CallCard(title, f"{head}\n✅ {call.accepted_by_name} さんが対応中です。", COLOR_GRAY)
    if call.status == "ended":
        return CallCard(title, f"{head}\n通話が終了しました。（対応者: {call.accepted_by_name}）", COLOR_GRAY)
    if call.status == "rejected":
        return CallCard(
            title,
            f"{head}\n対応できる担当者がいなかったため後ほどかけてくださいと案内しました",
            COLOR_NG,
        )
    if call.status == "timeout":
        minutes = max(1, settings.extension_ring_timeout_seconds // 60)
        return CallCard(
            title,
            f"{head}\n{minutes}分以内に出られなかったので、後ほどかけてくださいと案内しておきました。",
            COLOR_NG,
        )
    return CallCard(
        title,
        f"{head}\n通話準備に失敗しました...後ほどかけてくださいと案内しておきました。",
        COLOR_NG,
    )


async def _render(call: ExtensionCall, only_user: str | None = None) -> None:
    """送った DM を今の状態で描き直す。only_user を指定するとその人の分だけ。"""
    notifier = get_notifier()
    for ref in _refs(call):
        if only_user is not None and ref.user_id != only_user:
            continue
        try:
            await notifier.edit(ref, card_for(call, ref.user_id))
        except Exception as e:  # 通知の失敗で通話の流れは止めない
            logger.error(f"DM 編集に失敗: call={call.id} user={ref.user_id}: {e}")


# ---------------------------------------------------------------------------
# 状態遷移
# ---------------------------------------------------------------------------

async def get_call(db: AsyncSession, call_id: int) -> ExtensionCall | None:
    return await db.get(ExtensionCall, call_id)


def status_line(call: ExtensionCall) -> str:
    """Asterisk が読む 1 行の状態。"""
    if call.status == "accepted":
        return f"ACCEPTED {call.webrtc_slot or ''}".rstrip()
    return call.status.upper()


async def start_call(db: AsyncSession, phone_number: str, extension: str) -> tuple[str, ExtensionCall | None]:
    """内線呼び出しを開始する。戻り値: ("RINGING", call) / ("CLOSED", None) / ("UNKNOWN", None) / ("ERROR", call)"""
    cfg = load_extensions().get(extension)
    if cfg is None:
        logger.info(f"内線 未登録: {extension} from {phone_number}")
        return "UNKNOWN", None
    if not is_open():
        logger.info(f"内線 受付時間外: {extension} from {phone_number}")
        return "CLOSED", None

    call = ExtensionCall(
        phone_number=phone_number,
        extension=extension,
        status="ringing",
        join_secret=secrets.token_urlsafe(24),
        recipients=json.dumps(cfg["discord_user_ids"]),
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    notifier = get_notifier()

    async def send_one(uid: str) -> dict | None:
        try:
            ref = await notifier.send(uid, card_for(call, uid))
        except Exception as e:
            logger.error(f"DM 送信に失敗: call={call.id} user={uid}: {e}")
            return None
        return ref.to_dict() if ref else None

    # 全員に同時送信 (順番に送ると人数分の時間がかかり、Asterisk 側の待ち時間を超える)
    results = await asyncio.gather(*(send_one(uid) for uid in cfg["discord_user_ids"]))
    refs = [r for r in results if r]
    call.notifications = json.dumps(refs)
    if not refs:
        # 誰にも届かなければ待たせても無駄なので即エラー
        call.status = "error"
        call.ended_at = datetime.now(timezone.utc)
        await db.commit()
        logger.error(f"内線 通知先なし: call={call.id} ext={extension}")
        return "ERROR", call
    await db.commit()
    logger.info(f"内線 呼び出し開始: call={call.id} ext={extension} from={phone_number} to={len(refs)}人")
    # 送信中に誰かがボタンを押していた場合 (DM の参照を保存する前だった) は、今の状態で描き直す
    await db.refresh(call)
    if call.status != "ringing" or json.loads(call.rejected_by or "[]"):
        await _render(call)
    return "RINGING", call


async def accept(db: AsyncSession, call_id: int, user_id: str, user_name: str) -> ExtensionCall | None:
    """「出る」。最初の 1 人だけが担当になる (UPDATE ... WHERE status='ringing' で競合を防ぐ)。"""
    result = await db.execute(
        update(ExtensionCall)
        .where(ExtensionCall.id == call_id, ExtensionCall.status == "ringing")
        .values(
            status="accepted",
            accepted_by=user_id,
            accepted_by_name=user_name,
            accepted_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    call = await get_call(db, call_id)
    if call is None:
        return None
    await db.refresh(call)
    if result.rowcount == 0:
        # 既に誰かが取った / 終わっている → 押した人の DM を最新状態にするだけ
        await _render(call, only_user=user_id)
        return call

    slot = await pick_free_slot(db)
    if slot is None:
        logger.error(f"内線 空きスロットなし: call={call.id} (WEBRTC_SLOTS={settings.webrtc_slots})")
        call.status = "error"
        call.ended_at = datetime.now(timezone.utc)
    else:
        call.webrtc_slot = slot
        logger.info(f"内線 応答: call={call.id} by={user_name}({user_id}) slot={slot}")
    await db.commit()
    await _render(call)
    return call


async def reject(db: AsyncSession, call_id: int, user_id: str) -> ExtensionCall | None:
    """「拒否」。通知先の全員が拒否したら rejected。"""
    call = await get_call(db, call_id)
    if call is None:
        return None
    if call.status != "ringing":
        await _render(call, only_user=user_id)
        return call
    rejected = set(json.loads(call.rejected_by or "[]"))
    rejected.add(user_id)
    call.rejected_by = json.dumps(sorted(rejected))
    recipients = set(json.loads(call.recipients or "[]"))
    everyone_rejected = recipients <= rejected
    if everyone_rejected:
        call.status = "rejected"
        call.ended_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(f"内線 拒否: call={call.id} by={user_id} all={everyone_rejected}")
    await _render(call, only_user=None if everyone_rejected else user_id)
    return call


async def timeout(db: AsyncSession, call_id: int) -> ExtensionCall | None:
    call = await get_call(db, call_id)
    if call is None:
        return None
    if call.status == "ringing":
        call.status = "timeout"
        call.ended_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"内線 応答なし: call={call.id}")
        await _render(call)
    return call


async def ended(db: AsyncSession, call_id: int) -> ExtensionCall | None:
    call = await get_call(db, call_id)
    if call is None:
        return None
    if call.status == "accepted":
        call.status = "ended"
        call.ended_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"内線 通話終了: call={call.id}")
        await _render(call)
    elif call.status == "ringing":
        # 呼び出し中に発信者が切った
        call.status = "timeout"
        call.ended_at = datetime.now(timezone.utc)
        await db.commit()
        await _render(call)
    return call
