from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from arkpg.core.config import get_settings
from arkpg.db.base import Base
from arkpg.db import models  # noqa: F401

settings = get_settings()
engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def ensure_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_game_config_columns)


def _ensure_game_config_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    existing_columns = {column["name"] for column in inspector.get_columns("game_config")}

    if "boss_channel_id" in existing_columns:
        return

    dialect = sync_conn.dialect.name
    if dialect in {"mysql", "mariadb"}:
        sync_conn.execute(text("ALTER TABLE game_config ADD COLUMN boss_channel_id BIGINT NULL"))
        return

    if dialect == "sqlite":
        sync_conn.execute(text("ALTER TABLE game_config ADD COLUMN boss_channel_id INTEGER"))
        return

    sync_conn.execute(text("ALTER TABLE game_config ADD COLUMN boss_channel_id BIGINT"))
