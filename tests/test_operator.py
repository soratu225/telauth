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
