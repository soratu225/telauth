"""
app/models.py - データベースモデル定義
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PhoneSecret(Base):
    """電話番号ごとのTOTPシークレット管理テーブル。"""

    __tablename__ = "phone_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    # Fernetで暗号化したTOTPシークレット（Base32）
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_called_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<PhoneSecret phone_number={self.phone_number!r}>"


class CallLog(Base):
    """発着信ログテーブル。レート制限チェックにも使用。15年保管。"""

    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="initiated"
    )
    otp_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CallLog phone_number={self.phone_number!r} otp={self.otp_code!r} duration={self.duration_seconds!r}>"


class ExtensionCall(Base):
    """内線呼び出し (メニュー 4 → 内線番号入力 → Discord で担当者を呼ぶ) の状態。"""

    __tablename__ = "extension_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    # ringing / accepted / rejected / timeout / ended / error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ringing")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    accepted_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # RealtimeKit の会議IDと、担当者が参加ページで使う認証トークン
    meeting_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rtk_auth_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 参加ページ URL の秘密 (Discord の DM に載せる)
    join_secret: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # JSON: 通知先の Discord ユーザーID一覧 / 拒否したユーザーID一覧 / 送った DM の参照
    recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rejected_by: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notifications: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    def __repr__(self) -> str:
        return f"<ExtensionCall id={self.id} ext={self.extension!r} status={self.status!r}>"
