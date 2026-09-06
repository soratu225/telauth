"""
app/routers/extension.py - 内線呼び出しの API と担当者用の参加ページ

Asterisk 内部呼び出し (INTERNAL_TOKEN 設定時は X-Internal-Token 必須、応答は 1 行のテキスト):
  GET /api/v1/extension-call?phone_number=&extension=   呼び出し開始 → "RINGING <id>" / "CLOSED" / "UNKNOWN" / "ERROR <id>"
  GET /api/v1/extension-call/{id}/status                "RINGING" / "ACCEPTED <meeting_id>" / "REJECTED" / "TIMEOUT" / "ENDED" / "ERROR"
  GET /api/v1/extension-call/{id}/timeout               応答なしで打ち切った
  GET /api/v1/extension-call/{id}/ended                 通話が終わった (切断時)
運営者向け (X-API-Key):
  GET /api/v1/extension-calls                           内線呼び出しの一覧
担当者向け:
  GET /ext/join/{id}?t=<join_secret>                    RealtimeKit の通話ページ (https で公開すること)
"""
import html
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import extension_calls as svc
from app.database import get_db
from app.models import ExtensionCall
from app.routers.operator import verify_api_key, verify_internal_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["extension"])


class ExtensionCallInfo(BaseModel):
    id: int
    phone_number: str
    extension: str
    status: str
    created_at: datetime
    accepted_at: datetime | None
    ended_at: datetime | None
    accepted_by: str | None
    accepted_by_name: str | None
    meeting_id: str | None


@router.get(
    "/api/v1/extension-call",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
    response_class=PlainTextResponse,
)
async def extension_call_start(phone_number: str, extension: str, db: AsyncSession = Depends(get_db)):
    state, call = await svc.start_call(db, phone_number, extension)
    return f"{state} {call.id}" if call else state


@router.get(
    "/api/v1/extension-call/{call_id}/status",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
    response_class=PlainTextResponse,
)
async def extension_call_status(call_id: int, db: AsyncSession = Depends(get_db)):
    call = await svc.get_call(db, call_id)
    return svc.status_line(call) if call else "UNKNOWN"


@router.get(
    "/api/v1/extension-call/{call_id}/timeout",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
    response_class=PlainTextResponse,
)
async def extension_call_timeout(call_id: int, db: AsyncSession = Depends(get_db)):
    call = await svc.timeout(db, call_id)
    return svc.status_line(call) if call else "UNKNOWN"


@router.get(
    "/api/v1/extension-call/{call_id}/ended",
    include_in_schema=False,
    dependencies=[Depends(verify_internal_token)],
    response_class=PlainTextResponse,
)
async def extension_call_ended(call_id: int, db: AsyncSession = Depends(get_db)):
    call = await svc.ended(db, call_id)
    return svc.status_line(call) if call else "UNKNOWN"


@router.get(
    "/api/v1/extension-calls",
    response_model=list[ExtensionCallInfo],
    summary="内線呼び出しの一覧を取得する",
    dependencies=[Depends(verify_api_key)],
)
async def list_extension_calls(limit: int = 200, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExtensionCall).order_by(ExtensionCall.created_at.desc()).limit(limit))
    return [ExtensionCallInfo.model_validate(r, from_attributes=True) for r in result.scalars().all()]


_JOIN_PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script type="module">
  import { defineCustomElements } from "https://cdn.jsdelivr.net/npm/@cloudflare/realtimekit-ui@latest/loader/index.es2017.js";
  defineCustomElements();
</script>
<script src="https://cdn.jsdelivr.net/npm/@cloudflare/realtimekit@latest/dist/browser.js"></script>
<style>
  html, body { margin: 0; height: 100%; background: #111; color: #eee; font-family: system-ui, sans-serif; }
  rtk-meeting { height: 100vh; }
  .msg { padding: 2em; }
</style>
</head>
<body>
<rtk-meeting id="meeting" show-setup-screen="true"></rtk-meeting>
<script>
  const authToken = __TOKEN__;
  RealtimeKitClient.init({ authToken })
    .then((meeting) => { document.getElementById("meeting").meeting = meeting; })
    .catch((e) => { document.body.innerHTML = '<p class="msg">接続に失敗しました: ' + e + '</p>'; });
</script>
</body>
</html>"""


@router.get("/ext/join/{call_id}", include_in_schema=False, response_class=HTMLResponse)
async def join_page(call_id: int, t: str = "", db: AsyncSession = Depends(get_db)):
    """担当者が Discord のリンクから開く通話ページ。"""
    call = await svc.get_call(db, call_id)
    if call is None or not t or t != call.join_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")
    if call.status != "accepted" or not call.rtk_auth_token:
        return HTMLResponse(
            f'<!doctype html><meta charset="utf-8"><p style="font-family:system-ui;padding:2em">'
            f"この通話は終了しています（状態: {html.escape(call.status)}）。</p>"
        )
    title = f"内線{html.escape(call.extension)} {html.escape(svc.format_phone(call.phone_number))}"
    page = _JOIN_PAGE.replace("__TITLE__", title).replace("__TOKEN__", json.dumps(call.rtk_auth_token))
    return HTMLResponse(page)
