"""
app/routers/extension.py - 内線呼び出しの API と担当者用の参加ページ

Asterisk 内部呼び出し (INTERNAL_TOKEN 設定時は X-Internal-Token 必須、応答は 1 行のテキスト):
  GET /api/v1/extension-call?phone_number=&extension=   呼び出し開始 → "RINGING <id>" / "CLOSED" / "UNKNOWN" / "ERROR <id>"
  GET /api/v1/extension-call/{id}/status                "RINGING" / "ACCEPTED <slot>" / "REJECTED" / "TIMEOUT" / "ENDED" / "ERROR"
  GET /api/v1/extension-call/{id}/timeout               応答なしで打ち切った
  GET /api/v1/extension-call/{id}/ended                 通話が終わった (切断時)
運営者向け (X-API-Key):
  GET /api/v1/extension-calls                           内線呼び出しの一覧
担当者向け:
  GET /ext/join/{id}?t=<join_secret>                    通話ページ (JsSIP で Asterisk に WebSocket 登録。https で公開すること)
  WS  /ws                                               ブラウザ ↔ Asterisk (ws://127.0.0.1:8088/ws) の SIP over WebSocket 中継
"""
import asyncio
import html
import json
import logging
from datetime import datetime

import websockets
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import extension_calls as svc
from app.config import get_settings
from app.database import get_db
from app.models import ExtensionCall
from app.routers.operator import verify_api_key, verify_internal_token

logger = logging.getLogger(__name__)
settings = get_settings()
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
    webrtc_slot: str | None


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
<script src="/static/jssip-3.13.8.min.js"></script>
<style>
  :root { color-scheme: dark; }
  html, body { margin: 0; min-height: 100%; background: #111; color: #eee; font-family: system-ui, -apple-system, sans-serif; }
  main { max-width: 480px; margin: 0 auto; padding: 2.5rem 1.25rem; text-align: center; }
  h1 { font-size: 1.1rem; font-weight: 500; color: #aaa; margin: 0 0 .5rem; }
  .caller { font-size: 2rem; font-weight: 700; letter-spacing: .02em; margin: 0 0 2rem; }
  button { font: inherit; font-size: 1.25rem; padding: 1rem 2rem; border: 0; border-radius: 999px; cursor: pointer; min-width: 14rem; }
  #answer { background: #2ecc71; color: #062; }
  #hangup { background: #e74c3c; color: #fff; display: none; }
  button:disabled { opacity: .5; cursor: default; }
  #status { margin-top: 1.5rem; font-size: 1rem; color: #ccc; min-height: 1.5em; }
  #detail { margin-top: .5rem; font-size: .85rem; color: #777; }
</style>
</head>
<body>
<main>
  <h1>__LABEL__ への着信</h1>
  <p class="caller">__CALLER__</p>
  <button id="answer">電話に出る</button>
  <button id="hangup">切る</button>
  <p id="status">「電話に出る」を押すと接続します。</p>
  <p id="detail"></p>
  <audio id="remote" autoplay playsinline></audio>
</main>
<script>
(() => {
  const cfg = __CONFIG__;
  const $ = (id) => document.getElementById(id);
  const answerBtn = $("answer"), hangupBtn = $("hangup"), statusEl = $("status"), detailEl = $("detail"), audio = $("remote");
  let ua = null, session = null;
  const setStatus = (t, d) => { statusEl.textContent = t; detailEl.textContent = d || ""; };

  answerBtn.addEventListener("click", async () => {
    answerBtn.disabled = true;
    setStatus("マイクを準備しています…");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      stream.getTracks().forEach((t) => t.stop());
    } catch (e) {
      setStatus("マイクが使えません。ブラウザの許可設定を確認してください。", String(e));
      answerBtn.disabled = false;
      return;
    }
    setStatus("接続しています…");
    try {
      const socket = new JsSIP.WebSocketInterface(cfg.wsUrl);
      ua = new JsSIP.UA({
        sockets: [socket],
        uri: "sip:" + cfg.user + "@" + cfg.domain,
        password: cfg.password,
        display_name: cfg.displayName,
        register: true,
        register_expires: 120,
        session_timers: false,
      });
    } catch (e) {
      setStatus("接続設定に問題があります。管理者に連絡してください。", String(e));
      answerBtn.disabled = false;
      return;
    }
    ua.on("registered", () => { setStatus("準備できました。まもなく電話がつながります…"); hangupBtn.style.display = "inline-block"; });
    ua.on("registrationFailed", (e) => setStatus("接続に失敗しました。", "registration: " + (e.cause || "")));
    ua.on("disconnected", () => { if (!session) setStatus("サーバーとの接続が切れました。ページを再読み込みしてください。"); });
    ua.on("newRTCSession", ({ session: s }) => {
      if (s.direction !== "incoming") return;
      session = s;
      s.on("peerconnection", ({ peerconnection }) => {
        peerconnection.addEventListener("track", (ev) => { audio.srcObject = ev.streams[0]; audio.play().catch(() => {}); });
      });
      s.on("confirmed", () => setStatus("通話中"));
      s.on("ended", () => { setStatus("通話が終了しました。このページは閉じて大丈夫です。"); hangupBtn.style.display = "none"; ua.stop(); });
      s.on("failed", (e) => { setStatus("通話に失敗しました。", e.cause || ""); hangupBtn.style.display = "none"; ua.stop(); });
      s.answer({
        mediaConstraints: { audio: true, video: false },
        pcConfig: { iceServers: [{ urls: "stun:stun.l.google.com:19302" }] },
      });
      setStatus("つないでいます…");
    });
    ua.start();
  });

  hangupBtn.addEventListener("click", () => {
    if (session) { try { session.terminate(); } catch (e) {} }
    else if (ua) { ua.stop(); setStatus("待機をやめました。"); hangupBtn.style.display = "none"; }
  });
  window.addEventListener("beforeunload", () => { try { session && session.terminate(); ua && ua.stop(); } catch (e) {} });
})();
</script>
</body>
</html>"""


def _ws_url(request: Request) -> str:
    """ブラウザが使う WebSocket の URL。PUBLIC_BASE_URL があればそれを、無ければリクエスト元から組み立てる。"""
    base = svc.public_base_url()
    if not base:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        base = f"{proto}://{request.headers.get('host', request.url.netloc)}"
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"


@router.get("/ext/join/{call_id}", include_in_schema=False, response_class=HTMLResponse)
async def join_page(call_id: int, request: Request, t: str = "", db: AsyncSession = Depends(get_db)):
    """担当者が Discord のリンクから開く通話ページ。JsSIP で Asterisk に登録し、着信を自動応答する。"""
    call = await svc.get_call(db, call_id)
    if call is None or not t or t != call.join_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ページが見つかりません")
    if call.status != "accepted" or not call.webrtc_slot:
        return HTMLResponse(
            f'<!doctype html><meta charset="utf-8"><p style="font-family:system-ui;padding:2em">'
            f"この通話は終了しています（状態: {html.escape(call.status)}）。</p>"
        )
    label = svc.load_extensions().get(call.extension, {}).get("label", f"内線{call.extension}")
    caller = svc.format_phone(call.phone_number)
    config = {
        "wsUrl": _ws_url(request),
        "user": call.webrtc_slot,
        "password": svc.slot_password(call.webrtc_slot),
        "domain": settings.sip_domain,
        "displayName": call.accepted_by_name or "staff",
    }
    page = (
        _JOIN_PAGE.replace("__TITLE__", html.escape(f"{label} {caller}"))
        .replace("__LABEL__", html.escape(f"{label}（内線 {call.extension}）"))
        .replace("__CALLER__", html.escape(caller))
        .replace("__CONFIG__", json.dumps(config))
    )
    return HTMLResponse(page)


@router.websocket("/ws")
async def sip_websocket_proxy(websocket: WebSocket):
    """ブラウザの SIP over WebSocket を Asterisk (127.0.0.1:8088) へ中継する。サブプロトコルは sip。"""
    await websocket.accept(subprotocol="sip")
    try:
        upstream = await websockets.connect(settings.asterisk_ws_url, subprotocols=["sip"], open_timeout=10)
    except Exception as e:
        logger.error(f"Asterisk WebSocket に接続できません ({settings.asterisk_ws_url}): {e}")
        await websocket.close(code=1011)
        return

    async def browser_to_asterisk():
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("text") if msg.get("text") is not None else msg.get("bytes")
            if data is not None:
                await upstream.send(data)

    async def asterisk_to_browser():
        async for data in upstream:
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)

    tasks = [asyncio.create_task(browser_to_asterisk()), asyncio.create_task(asterisk_to_browser())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, websockets.ConnectionClosed)):
                logger.warning(f"WebSocket 中継エラー: {exc}")
    finally:
        await upstream.close()
        try:
            await websocket.close()
        except Exception:
            pass
