"""
app/database.py - SQLAlchemy 非同期データベース設定
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def _add_missing_columns(conn) -> None:
    """既存テーブルにモデル側で増えた列を ALTER TABLE ADD COLUMN で足す (SQLite 向けの簡易マイグレーション)。"""
    inspector = inspect(conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(dialect=conn.dialect)}"
            default = getattr(col.default, "arg", None)
            if default is not None and not callable(default):
                ddl += f" DEFAULT {default!r}" if isinstance(default, str) else f" DEFAULT {default}"
            elif not col.nullable:
                ddl += " DEFAULT ''"
            logger.info(f"列を追加: {ddl}")
            conn.execute(text(ddl))


async def init_db() -> None:
    """テーブルを作成し、足りない列を追加する（アプリ起動時に呼び出す）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_db():
    """FastAPI依存性注入用のDBセッションジェネレータ。"""
    async with AsyncSessionLocal() as session:
        yield session
