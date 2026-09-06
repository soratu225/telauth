"""
tests/test_operator.py - 運営者向けAPI / Asteriskコールバックのテスト
"""
import pytest

from app.config import get_settings
from app.models import CallLog
from tests.conftest import TestSessionLocal


def test_api_key_env_var_is_honored():
    """README/.env.example で案内している API_KEY 環境変数が設定に反映される。"""
    assert get_settings().api_keys == ["test-api-key"]


async def test_operator_api_accepts_configured_key(client):
    resp = await client.get("/api/v1/phones")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_operator_api_rejects_wrong_key(client):
    resp = await client.get("/api/v1/phones", headers={"X-API-Key": "changeme"})
    assert resp.status_code == 401


async def _insert_inbound_log(phone_number: str) -> int:
    async with TestSessionLocal() as session:
        log = CallLog(phone_number=phone_number, status="inbound_answered", otp_code="123456")
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log.id


async def _fetch_log(log_id: int) -> CallLog:
    async with TestSessionLocal() as session:
        return await session.get(CallLog, log_id)


@pytest.mark.parametrize(
    "raw_duration, expected",
    [("42", 42), ("", 0), ("abc", 0), ("-5", 0), ("12.7", 12)],
)
async def test_call_complete_tolerates_dialplan_duration(client, raw_duration, expected):
    """ダイヤルプランの変数展開で duration が空文字等になっても 422 にならず記録される。"""
    log_id = await _insert_inbound_log("09012341234")

    resp = await client.get(
        "/api/v1/call-complete",
        params={"phone_number": "09012341234", "duration": raw_duration},
    )
    assert resp.status_code == 200, resp.text

    log = await _fetch_log(log_id)
    assert log.status == "completed"
    assert log.duration_seconds == expected


async def test_call_complete_without_duration_param(client):
    log_id = await _insert_inbound_log("09012341234")
    resp = await client.get("/api/v1/call-complete", params={"phone_number": "09012341234"})
    assert resp.status_code == 200
    log = await _fetch_log(log_id)
    assert log.duration_seconds == 0


# ---------------------------------------------------------------------------
# 認証コード発行 / 電話での照合 / 認証状態
# ---------------------------------------------------------------------------

PHONE = "09012341234"


async def _issue_code(client, phone=PHONE) -> str:
    resp = await client.post("/api/v1/code", json={"phone_number": phone})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone_number"] == phone
    assert len(body["code"]) == 6 and body["code"].isdigit()
    assert 0 < body["expires_in_seconds"] <= get_settings().otp_interval_seconds
    return body["code"]


async def _verify(client, code, phone=PHONE, headers=None):
    return await client.get(
        "/api/v1/inbound-verify",
        params={"phone_number": phone, "code": code},
        headers=headers or {},
    )


async def _status(client, phone=PHONE):
    resp = await client.get("/api/v1/auth-status", params={"phone_number": phone})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_code_endpoint_requires_api_key(client):
    resp = await client.post("/api/v1/code", json={"phone_number": PHONE}, headers={"X-API-Key": "bad"})
    assert resp.status_code == 401


async def test_code_matches_phone_secret(client):
    code = await _issue_code(client)
    secret = (await client.get(f"/api/v1/phones/{PHONE}/secret")).json()["secret"]
    from app.otp import verify_otp
    assert verify_otp(secret, code)


async def test_inbound_logs_call_without_tts(client):
    resp = await client.get("/api/v1/inbound", params={"phone_number": PHONE})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    logs = (await client.get("/api/v1/logs", params={"phone_number": PHONE})).json()
    assert logs[0]["status"] == "inbound_answered"
    assert logs[0]["otp_code"] is None


async def test_phone_verification_success(client):
    code = await _issue_code(client)
    assert (await _status(client))["verified"] is False

    resp = await _verify(client, code)
    assert resp.status_code == 200
    assert resp.json() == {"valid": True}

    st = await _status(client)
    assert st["verified"] is True
    assert st["verified_at"] is not None

    logs = (await client.get("/api/v1/logs", params={"phone_number": PHONE})).json()
    assert logs[0]["status"] == "verified"


async def test_phone_verification_wrong_code(client):
    code = await _issue_code(client)
    wrong = "000000" if code != "000000" else "111111"
    resp = await _verify(client, wrong)
    assert resp.status_code == 401
    assert resp.json()["detail"]["reason"] == "mismatch"
    assert (await _status(client))["verified"] is False
    logs = (await client.get("/api/v1/logs", params={"phone_number": PHONE})).json()
    assert logs[0]["status"] == "verify_failed"


async def test_someone_elses_code_is_rejected(client):
    """他人の番号に発行されたコードは、発信者番号のシークレットと合わないので失敗する。"""
    other_code = await _issue_code(client, phone="08099998888")
    await _issue_code(client)  # 自分の番号も登録
    resp = await _verify(client, other_code)  # 自分の番号から他人のコードを入力
    assert resp.status_code == 401


async def test_unregistered_phone_is_rejected(client):
    resp = await _verify(client, "123456", phone="07000000000")
    assert resp.status_code == 401
    assert resp.json()["detail"]["reason"] == "unregistered"


async def test_lockout_after_too_many_failures(client):
    code = await _issue_code(client)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(get_settings().verify_max_failures):
        assert (await _verify(client, wrong)).status_code == 401
    resp = await _verify(client, code)  # ロック後は正しいコードでも拒否
    assert resp.status_code == 401
    assert resp.json()["detail"]["reason"] == "locked"


async def test_internal_token_guards_asterisk_endpoints(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "internal_token", "secret-token")
    code = await _issue_code(client)

    assert (await _verify(client, code)).status_code == 401
    assert (await client.get("/api/v1/inbound", params={"phone_number": PHONE})).status_code == 401
    assert (await client.get("/api/v1/call-complete", params={"phone_number": PHONE})).status_code == 401

    ok = await _verify(client, code, headers={"X-Internal-Token": "secret-token"})
    assert ok.status_code == 200
