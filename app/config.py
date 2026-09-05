"""
app/config.py - 環境変数設定管理（Asterisk/SIP対応版）
"""
import logging
from functools import lru_cache
from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # サービス設定
    service_name: str = "アピレンティック電話認証サービス"
    api_keys_str: str = "changeme"  # カンマ区切りで複数指定可能
    secret_encryption_key: str = ""

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.api_keys_str.split(",") if k.strip()]

    # Brastel SIP 設定（主にDocker-Compose経由でAsteriskが利用する想定ですが、発信者番号はAPIでも使用）
    brastel_sip_server: str = "sip.brastel.ne.jp"
    brastel_sip_username: str = ""
    brastel_sip_password: str = ""
    brastel_sip_caller_id: str = ""

    # Asterisk AMI 設定
    asterisk_host: str = "127.0.0.1"
    asterisk_ami_port: int = 5038
    asterisk_ami_username: str = "telauth"
    asterisk_ami_password: str = "ami-secret"
    asterisk_context: str = "outbound-otp"
    asterisk_endpoint: str = "brastel-endpoint"
    asterisk_call_timeout_ms: int = 30000

    # TTS設定
    tts_lang: str = "ja"
    tts_sounds_dir: str = "/var/lib/asterisk/sounds/telauth"

    # OTP設定
    otp_interval_seconds: int = 900  # 15分
    otp_digits: int = 6
    call_rate_limit_seconds: int = 300  # 5分

    # データベース
    database_url: str = "sqlite+aiosqlite:///./telauth.db"

    def get_fernet_key(self) -> bytes:
        if self.secret_encryption_key:
            key = self.secret_encryption_key.encode()
            Fernet(key)
            return key
        else:
            key = Fernet.generate_key()
            logger.warning(
                "SECRET_ENCRYPTION_KEY が未設定のため一時的なキーを生成しました。"
                f"本番環境では .env に以下を設定してください: SECRET_ENCRYPTION_KEY={key.decode()}"
            )
            return key

@lru_cache
def get_settings() -> Settings:
    return Settings()
