"""
app/realtimekit.py - Cloudflare RealtimeKit REST API クライアント

会議の作成と参加者 (担当者) の追加だけを行う。
  POST /accounts/{account_id}/realtime/kit/{app_id}/meetings
  POST /accounts/{account_id}/realtime/kit/{app_id}/meetings/{meeting_id}/participants
認証は Cloudflare API トークン (Bearer)。
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class RealtimeKitError(Exception):
    pass


class RealtimeKitClient:
    def __init__(self, account_id: str, api_token: str, app_id: str, preset_name: str):
        self.account_id = account_id
        self.api_token = api_token
        self.app_id = app_id
        self.preset_name = preset_name

    @property
    def configured(self) -> bool:
        return bool(self.account_id and self.api_token and self.app_id)

    @property
    def base_url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/realtime/kit/{self.app_id}"

    async def _post(self, path: str, body: dict) -> dict:
        if not self.configured:
            raise RealtimeKitError("RealtimeKit が未設定です (CF_ACCOUNT_ID / CF_API_TOKEN / REALTIMEKIT_APP_ID)")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400 or not payload.get("success", True):
            raise RealtimeKitError(f"RealtimeKit API エラー {resp.status_code}: {resp.text[:300]}")
        return payload.get("data", payload)

    async def create_meeting(self, title: str) -> str:
        """会議を作成して meeting id を返す。"""
        data = await self._post("/meetings", {"title": title})
        meeting_id = data.get("id")
        if not meeting_id:
            raise RealtimeKitError(f"会議IDが取得できません: {data}")
        return meeting_id

    async def add_participant(self, meeting_id: str, name: str, custom_participant_id: str) -> str:
        """担当者を参加者として追加し、ブラウザ側で使う認証トークンを返す。"""
        data = await self._post(
            f"/meetings/{meeting_id}/participants",
            {
                "name": name,
                "preset_name": self.preset_name,
                "custom_participant_id": custom_participant_id,
            },
        )
        token = data.get("token") or data.get("authToken") or data.get("auth_token")
        if not token:
            raise RealtimeKitError(f"参加トークンが取得できません: {list(data.keys())}")
        return token


def build_client() -> RealtimeKitClient:
    s = get_settings()
    return RealtimeKitClient(s.cf_account_id, s.cf_api_token, s.realtimekit_app_id, s.realtimekit_preset_name)


_client: RealtimeKitClient | None = None


def get_realtimekit() -> RealtimeKitClient:
    global _client
    if _client is None:
        _client = build_client()
    return _client


def set_realtimekit(client: RealtimeKitClient) -> None:
    global _client
    _client = client
