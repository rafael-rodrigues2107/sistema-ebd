from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

# ── Engine ──────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

# For SQLite: enable WAL mode and foreign keys on connect
@event.listens_for(engine.sync_engine, "connect")
def _on_connect(dbapi_connection, _connection_record):
    if "sqlite" in settings.database_url:
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

# ── Session factory (unscoped) ──────────────────────────────────────────
_async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Scoped session (per-request with FastAPI) ───────────────────────────
AsyncScopedSession = async_scoped_session(
    _async_session_factory,
    scopefunc=None,  # caller must supply a scope; FastAPI does via middleware
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a scoped async session per request."""
    session = _async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Create all tables. Use only for dev / MVP; prefer Alembic for production."""
    from models import Base  # noqa: PLC0415 — deferred to avoid circular import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
