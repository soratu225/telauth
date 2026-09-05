"""
tests/conftest.py - テスト共通フィクスチャ
"""
import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# テスト用にインメモリSQLiteを使う
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("BRASTEL_DOMAIN", "test.domain")
os.environ.setdefault("BRASTEL_API_TOKEN", "test-token")
os.environ.setdefault("IVR_SECRET_TOKEN", "")  # テスト中は無効化
os.environ.setdefault("SECRET_ENCRYPTION_KEY", "")

from app.config import get_settings
from app.database import Base, get_db
from app.main import app

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TestSessionLocal = async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_db():
    """各テスト前にテーブルを作成し、テスト後に破棄する。"""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "test-api-key"},
    ) as c:
        yield c
