"""
tests/test_extension.py - 内線呼び出し (Discord 通知 / RealtimeKit) のテスト。外部サービスはフェイクに差し替える。
"""
import json
from datetime import datetime, timezone

import pytest

from app import extension_calls as svc
from app.config import get_settings
from app.notify import CallCard, NotificationRef, set_notifier, NullNotifier
from tests.conftest import TestSessionLocal

settings = get_settings()
CALLER = "08012345678"
STAFF = ["1001", "1002", "1003"]


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[str, CallCard]] = []
        self.edits: list[tuple[NotificationRef, CallCard]] = []
        self.fail_send = False
        self._n = 0

    async def send(self, user_id, card):
        if self.fail_send:
            raise RuntimeError("discord down")
        self._n += 1
        self.sent.append((user_id, card))
        return NotificationRef(user_id=user_id, channel_id=500 + int(user_id), message_id=self._n)

    async def edit(self, ref, card):
        self.edits.append((ref, card))

    def latest_card(self, user_id) -> CallCard:
        for ref, card in reversed(self.edits):
            if ref.user_id == user_id:
                return card
        for uid, card in reversed(self.sent):
            if uid == user_id:
                return card
        raise AssertionError(f"no card for {user_id}")


@pytest.fixture
def ext_env(monkeypatch, tmp_path):
    ext_file = tmp_path / "extensions.json"
    ext_file.write_text(json.dumps({
        "101": {"label": "サポート", "discord_user_ids": STAFF},
        "102": {"discord_user_ids": [STAFF[0]]},
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "extensions_file", str(ext_file))
    monkeypatch.setattr(settings, "extension_hours_start", 0)
    monkeypatch.setattr(settings, "extension_hours_end", 24)
    monkeypatch.setattr(settings, "public_base_url", "https://telauth.example.test")
    monkeypatch.setattr(svc, "session_factory", TestSessionLocal)
    monkeypatch.setattr(settings, "webrtc_secret", "test-secret")
    monkeypatch.setattr(settings, "webrtc_slots", 2)
    notifier = FakeNotifier()
    set_notifier(notifier)
    yield notifier, None
    set_notifier(NullNotifier())


async def _start(client, extension="101", phone=CALLER):
    resp = await client.get("/api/v1/extension-call", params={"phone_number": phone, "extension": extension})
    assert resp.status_code == 200, resp.text
    return resp.text


async def _status(client, call_id):
    resp = await client.get(f"/api/v1/extension-call/{call_id}/status")
    assert resp.status_code == 200
    return resp.text


def _buttons(card: CallCard):
    return [(b.label, b.style) for b in card.buttons]


# ---------------------------------------------------------------------------

def test_is_open_uses_configured_hours(monkeypatch):
    monkeypatch.setattr(settings, "extension_hours_start", 9)
    monkeypatch.setattr(settings, "extension_hours_end", 22)
    monkeypatch.setattr(settings, "extension_timezone", "Asia/Tokyo")
    # 2026-09-06 00:00 UTC = 09:00 JST → 受付中 / 13:00 UTC = 22:00 JST → 終了
    assert svc.is_open(datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc)) is True
    assert svc.is_open(datetime(2026, 9, 6, 12, 59, tzinfo=timezone.utc)) is True
    assert svc.is_open(datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc)) is False
    assert svc.is_open(datetime(2026, 9, 5, 23, 59, tzinfo=timezone.utc)) is False


@pytest.mark.parametrize("raw, shown", [
    ("08012345678", "080-1234-5678"),
    ("+818012345678", "080-1234-5678"),
    ("0312345678", "03-1234-5678"),
    ("0451234567", "045-123-4567"),
    ("0120123456", "0120-123-456"),
    ("anonymous", "anonymous"),
])
def test_format_phone(raw, shown):
    assert svc.format_phone(raw) == shown


async def test_start_notifies_every_staff_member(client, ext_env):
    notifier, _ = ext_env
    text = await _start(client)
    state, call_id = text.split()
    assert state == "RINGING"

    assert [uid for uid, _ in notifier.sent] == STAFF
    card = notifier.sent[0][1]
    assert card.title == "📞 080-1234-5678 からお電話です！"
    assert "サポート（内線 101）" in card.description
    assert _buttons(card) == [("出る", "success"), ("拒否", "danger")]
    assert card.buttons[0].custom_id == f"extcall:{call_id}:accept"
    assert await _status(client, call_id) == "RINGING"


async def test_unknown_extension_and_closed_hours(client, ext_env, monkeypatch):
    notifier, _ = ext_env
    assert await _start(client, extension="999") == "UNKNOWN"
    monkeypatch.setattr(settings, "extension_hours_start", 9)
    monkeypatch.setattr(settings, "extension_hours_end", 9)
    assert await _start(client) == "CLOSED"
    assert notifier.sent == []


async def test_start_without_reachable_staff_is_error(client, ext_env):
    notifier, _ = ext_env
    notifier.fail_send = True
    state, call_id = (await _start(client)).split()
    assert state == "ERROR"
    assert await _status(client, call_id) == "ERROR"


async def test_first_accept_wins_and_assigns_slot(client, ext_env):
    notifier, _ = ext_env
    _, call_id = (await _start(client)).split()
    call_id = int(call_id)

    async with TestSessionLocal() as db:
        call = await svc.accept(db, call_id, STAFF[1], "田中")
    assert call.status == "accepted"
    assert call.webrtc_slot == "web1"
    assert await _status(client, call_id) == "ACCEPTED web1"

    me = notifier.latest_card(STAFF[1])
    assert "あなたが対応中" in me.description
    assert _buttons(me) == [("通話に参加", "link")]
    assert me.buttons[0].url == f"https://telauth.example.test/ext/join/{call_id}?t={call.join_secret}"
    for other in (STAFF[0], STAFF[2]):
        card = notifier.latest_card(other)
        assert "田中 さんが対応中" in card.description
        assert card.buttons == []

    # 2 人目が押しても担当は変わらない
    async with TestSessionLocal() as db:
        call2 = await svc.accept(db, call_id, STAFF[2], "鈴木")
    assert call2.accepted_by == STAFF[1]
    assert call2.webrtc_slot == "web1"
    assert "田中 さんが対応中" in notifier.latest_card(STAFF[2]).description


async def test_slots_are_pooled_and_released(client, ext_env):
    ids = []
    for _ in range(3):
        _, cid = (await _start(client)).split()
        ids.append(int(cid))
    async with TestSessionLocal() as db:
        a = await svc.accept(db, ids[0], STAFF[0], "A")
        b = await svc.accept(db, ids[1], STAFF[1], "B")
        c = await svc.accept(db, ids[2], STAFF[2], "C")  # プールは 2 つ → 空きなし
    assert (a.webrtc_slot, b.webrtc_slot) == ("web1", "web2")
    assert c.status == "error" and c.webrtc_slot is None

    await client.get(f"/api/v1/extension-call/{ids[0]}/ended")  # web1 が空く
    _, cid = (await _start(client)).split()
    async with TestSessionLocal() as db:
        d = await svc.accept(db, int(cid), STAFF[0], "D")
    assert d.webrtc_slot == "web1"


def test_slot_password_matches_entrypoint_formula(monkeypatch):
    """entrypoint.sh: printf '%s' "$SECRET:$slot" | sha256sum | cut -c1-32"""
    import hashlib
    monkeypatch.setattr(settings, "webrtc_secret", "abc")
    assert svc.slot_password("web1") == hashlib.sha256(b"abc:web1").hexdigest()[:32]
    monkeypatch.setattr(settings, "webrtc_secret", "")
    monkeypatch.setattr(settings, "internal_token", "tok")
    assert svc.slot_password("web2") == hashlib.sha256(b"tok:web2").hexdigest()[:32]


async def test_rejected_only_when_everyone_rejects(client, ext_env):
    notifier, _ = ext_env
    _, call_id = (await _start(client)).split()
    call_id = int(call_id)

    async with TestSessionLocal() as db:
        await svc.reject(db, call_id, STAFF[0])
    assert await _status(client, call_id) == "RINGING"
    assert "拒否しました" in notifier.latest_card(STAFF[0]).description
    assert _buttons(notifier.latest_card(STAFF[1])) == [("出る", "success"), ("拒否", "danger")]

    async with TestSessionLocal() as db:
        await svc.reject(db, call_id, STAFF[1])
        await svc.reject(db, call_id, STAFF[2])
    assert await _status(client, call_id) == "REJECTED"
    for uid in STAFF:
        card = notifier.latest_card(uid)
        assert "全員が対応できなかった" in card.description
        assert card.buttons == []


async def test_single_staff_reject_ends_call(client, ext_env):
    _, call_id = (await _start(client, extension="102")).split()
    async with TestSessionLocal() as db:
        await svc.reject(db, int(call_id), STAFF[0])
    assert await _status(client, call_id) == "REJECTED"


async def test_timeout_and_ended(client, ext_env):
    notifier, _ = ext_env
    _, call_id = (await _start(client)).split()
    resp = await client.get(f"/api/v1/extension-call/{call_id}/timeout")
    assert resp.text == "TIMEOUT"
    for uid in STAFF:
        card = notifier.latest_card(uid)
        assert "応答がなかった" in card.description
        assert card.buttons == []

    _, call_id2 = (await _start(client)).split()
    async with TestSessionLocal() as db:
        await svc.accept(db, int(call_id2), STAFF[0], "佐藤")
    resp = await client.get(f"/api/v1/extension-call/{call_id2}/ended")
    assert resp.text == "ENDED"
    assert "通話が終了しました" in notifier.latest_card(STAFF[0]).description


async def test_join_page(client, ext_env):
    _, call_id = (await _start(client)).split()
    call_id = int(call_id)
    async with TestSessionLocal() as db:
        call = await svc.accept(db, call_id, STAFF[0], "佐藤")

    resp = await client.get(f"/ext/join/{call_id}", params={"t": "wrong"})
    assert resp.status_code == 404
    resp = await client.get(f"/ext/join/{call_id}", params={"t": call.join_secret})
    assert resp.status_code == 200
    assert "/static/jssip-3.13.8.min.js" in resp.text
    assert "080-1234-5678" in resp.text
    cfg = json.loads(resp.text.split("const cfg = ", 1)[1].split(";\n", 1)[0])
    assert cfg["wsUrl"] == "wss://telauth.example.test/ws"
    assert cfg["user"] == "web1"
    assert cfg["password"] == svc.slot_password("web1")
    assert cfg["displayName"] == "佐藤"

    await client.get(f"/api/v1/extension-call/{call_id}/ended")
    resp = await client.get(f"/ext/join/{call_id}", params={"t": call.join_secret})
    assert resp.status_code == 200
    assert "終了" in resp.text


async def test_join_page_ws_url_from_request_when_no_public_base(client, ext_env, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    _, call_id = (await _start(client)).split()
    async with TestSessionLocal() as db:
        call = await svc.accept(db, int(call_id), STAFF[0], "佐藤")
    resp = await client.get(f"/ext/join/{call_id}", params={"t": call.join_secret},
                            headers={"host": "tunnel.example.com", "x-forwarded-proto": "https"})
    assert '"wsUrl": "wss://tunnel.example.com/ws"' in resp.text


async def test_static_jssip_is_served(client):
    resp = await client.get("/static/jssip-3.13.8.min.js")
    assert resp.status_code == 200
    assert "WebSocketInterface" in resp.text


async def test_internal_endpoints_need_token(client, ext_env, monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "tok")
    resp = await client.get("/api/v1/extension-call", params={"phone_number": CALLER, "extension": "101"})
    assert resp.status_code == 401
    resp = await client.get("/api/v1/extension-call", params={"phone_number": CALLER, "extension": "101"},
                            headers={"X-Internal-Token": "tok"})
    assert resp.status_code == 200


async def test_operator_can_list_extension_calls(client, ext_env):
    _, call_id = (await _start(client)).split()
    resp = await client.get("/api/v1/extension-calls")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["id"] == int(call_id)
    assert rows[0]["status"] == "ringing"
    assert rows[0]["extension"] == "101"


@pytest.mark.parametrize("raw, expected", [
    ("https://telauth.example.com", "https://telauth.example.com"),
    ("https://telauth.example.com/", "https://telauth.example.com"),
    ("http://localhost:8000", "http://localhost:8000"),
    ("https://（通話ページを公開するURL）", ""),
    ("telauth.example.com", ""),
    ("", ""),
])
def test_public_base_url_validation(monkeypatch, raw, expected):
    monkeypatch.setattr(settings, "public_base_url", raw)
    assert svc.public_base_url() == expected


async def test_join_page_ignores_placeholder_public_base_url(client, ext_env, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://（通話ページを公開するURL）")
    _, call_id = (await _start(client)).split()
    async with TestSessionLocal() as db:
        call = await svc.accept(db, int(call_id), STAFF[0], "佐藤")
    resp = await client.get(f"/ext/join/{call_id}", params={"t": call.join_secret}, headers={"host": "localhost:18000"})
    assert '"wsUrl": "ws://localhost:18000/ws"' in resp.text
    # DM 側もリンクボタンではなくパス表記になる
    card = ext_env[0].latest_card(STAFF[0])
    assert card.buttons == [] and "/ext/join/" in card.description


async def test_client_log_requires_secret(client, ext_env):
    _, call_id = (await _start(client)).split()
    async with TestSessionLocal() as db:
        call = await svc.accept(db, int(call_id), STAFF[0], "佐藤")
    resp = await client.post(f"/ext/join/{call_id}/client-log", params={"t": "wrong"}, json={"event": "x"})
    assert resp.status_code == 404
    resp = await client.post(f"/ext/join/{call_id}/client-log", params={"t": call.join_secret},
                             json={"event": "failed", "detail": "User Denied Media Access", "ua": "Safari"})
    assert resp.status_code == 200
    page = (await client.get(f"/ext/join/{call_id}", params={"t": call.join_secret})).text
    assert f"/ext/join/{call_id}/client-log?t={call.join_secret}" in page
    assert "mediaStream: micStream" in page
    assert 'on("icecandidate"' in page and "ready()" in page
