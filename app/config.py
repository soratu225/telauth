"""
app/config.py - 環境変数設定管理（Asterisk/SIP対応版）
"""
import logging
from functools import lru_cache
from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field
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
    # 環境変数 API_KEY (README / .env.example で案内している名前) から読む。
    # カンマ区切りで複数指定可能。API_KEYS / API_KEYS_STR も後方互換で受け付ける。
    api_keys_str: str = Field(
        default="changeme",
        validation_alias=AliasChoices("API_KEY", "API_KEYS", "API_KEYS_STR"),
    )
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

    # Asterisk → API の内部呼び出し (/api/v1/inbound, /inbound-verify, /call-complete) を守るトークン。
    # 空なら検査しない (ポート8000をローカルに閉じている前提)。設定時はダイヤルプランが
    # ${ENV(INTERNAL_TOKEN)} を X-Internal-Token ヘッダで送る。
    internal_token: str = ""

    # OTP設定
    otp_interval_seconds: int = 900  # 15分
    otp_digits: int = 6
    call_rate_limit_seconds: int = 300  # 5分
    # 有効期間内に同じ番号でこれ以上コード照合に失敗したら、以後は正しいコードでも拒否する (総当たり対策)
    verify_max_failures: int = 5

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
