"""Async SQLAlchemy engine and session setup."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_db_url = get_settings().database_url
_connect_args: dict[str, object] = {}
if _db_url.startswith("postgresql+asyncpg") and (":6543" in _db_url or "pooler.supabase.com" in _db_url):
    _connect_args["statement_cache_size"] = 0

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a DB session."""
    async with async_session_factory() as session:
        yield session
