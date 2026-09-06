"""
app/notify.py - 担当者への通知 (Discord DM) の抽象化

内線サービス (extension_calls.py) は Notifier だけを使い、Discord の実装には依存しない。
テストでは FakeNotifier に差し替える。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class CardButton:
    label: str
    style: str  # "success" / "danger" / "link"
    custom_id: str | None = None
    url: str | None = None


@dataclass
class CallCard:
    """DM に表示する埋め込みの内容。"""

    title: str
    description: str
    color: int
    buttons: list[CardButton] = field(default_factory=list)


@dataclass
class NotificationRef:
    """送った DM を後で編集するための参照。"""

    user_id: str
    channel_id: int
    message_id: int

    def to_dict(self) -> dict:
        return {"user_id": self.user_id, "channel_id": self.channel_id, "message_id": self.message_id}

    @classmethod
    def from_dict(cls, d: dict) -> "NotificationRef":
        return cls(user_id=str(d["user_id"]), channel_id=int(d["channel_id"]), message_id=int(d["message_id"]))


class Notifier(Protocol):
    async def send(self, user_id: str, card: CallCard) -> NotificationRef | None: ...

    async def edit(self, ref: NotificationRef, card: CallCard) -> None: ...


class NullNotifier:
    """Discord 未設定時。ログに出すだけで誰にも届かない。"""

    async def send(self, user_id: str, card: CallCard) -> NotificationRef | None:
        logger.warning(f"Discord 未設定のため通知できません: to={user_id} title={card.title!r}")
        return None

    async def edit(self, ref: NotificationRef, card: CallCard) -> None:
        return None


_notifier: Notifier = NullNotifier()


def set_notifier(notifier: Notifier) -> None:
    global _notifier
    _notifier = notifier


def get_notifier() -> Notifier:
    return _notifier
