"""
app/otp.py - TOTP生成・検証・暗号化ロジック
"""
import pyotp
from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()
_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.get_fernet_key())
    return _fernet


# ---------------------------------------------------------------------------
# シークレット管理
# ---------------------------------------------------------------------------

def generate_secret() -> str:
    """新しいBase32 TOTPシークレットを生成する。"""
    return pyotp.random_base32()


def encrypt_secret(plain_secret: str) -> str:
    """TOTPシークレットをFernetで暗号化し、文字列として返す。"""
    return get_fernet().encrypt(plain_secret.encode()).decode()


def decrypt_secret(encrypted_secret: str) -> str:
    """暗号化されたTOTPシークレットを復号する。"""
    return get_fernet().decrypt(encrypted_secret.encode()).decode()


# ---------------------------------------------------------------------------
# OTP生成・検証
# ---------------------------------------------------------------------------

def get_totp(plain_secret: str) -> pyotp.TOTP:
    """TOTPオブジェクトを返す（設定値の間隔・桁数を使用）。"""
    return pyotp.TOTP(
        plain_secret,
        digits=settings.otp_digits,
        interval=settings.otp_interval_seconds,
    )


def generate_otp(plain_secret: str) -> str:
    """現在時刻に基づくOTPコードを生成する。"""
    return get_totp(plain_secret).now()


def verify_otp(plain_secret: str, code: str) -> bool:
    """OTPコードを検証する。有効期間内のトークンを受け付ける。"""
    totp = get_totp(plain_secret)
    # valid_window=1 で前後1インターバルも許容（時計のズレ対策）
    return totp.verify(code, valid_window=1)


def digits_to_speech(code: str) -> str:
    """OTPコードを読み上げ用の文字列に変換する。
    例: "123456" -> "1。2。3。4。5。6。"
    """
    return "。".join(list(code)) + "。"


def get_provisioning_uri(plain_secret: str, phone_number: str) -> str:
    """Google Authenticatorアプリ用のプロビジョニングURIを返す。"""
    totp = get_totp(plain_secret)
    return totp.provisioning_uri(
        name=phone_number,
        issuer_name=settings.service_name,
    )
