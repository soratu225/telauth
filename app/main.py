"""
app/main.py - FastAPI アプリケーションエントリーポイント
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.notify import set_notifier
from app.routers import extension, operator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時にDBを初期化し、Discord Bot (内線通知) を起動する。"""
    logger.info("データベースを初期化しています...")
    await init_db()

    bot = None
    if settings.discord_bot_token:
        from app.discord_bot import DiscordNotifier

        bot = DiscordNotifier(settings.discord_bot_token)
        set_notifier(bot)
        await bot.start()
        logger.info("Discord Bot を起動しました (内線通知)")
    else:
        logger.warning("DISCORD_BOT_TOKEN が未設定のため、内線の呼び出し通知は送られません")

    logger.info(f"サービス起動: {settings.service_name}")
    yield
    logger.info("サービスを停止しています...")
    if bot:
        await bot.stop()

app = FastAPI(
    title="電話OTP認証サービス API",
    description=(
        "Brastel SIP + Asterisk を利用して電話でOTPを読み上げる認証サービスです。\n\n"
        "## 認証\n"
        "運営者向けAPIは `X-API-Key` ヘッダーで認証します。\n\n"
        "## OTPについて\n"
        f"TOTP方式（RFC 6238）。有効期間: {settings.otp_interval_seconds // 60}分。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(operator.router)
app.include_router(extension.router)

@app.get("/", include_in_schema=False)
async def root():
    return {"service": settings.service_name, "status": "ok"}

@app.get("/health", tags=["system"], summary="ヘルスチェック")
async def health():
    return {"status": "ok", "service": settings.service_name}
