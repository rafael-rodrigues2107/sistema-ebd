from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from tenant import igreja_atual

# ── Engine ──────────────────────────────────────────────────────────────
_opcoes_pool = {"poolclass": NullPool} if settings.db_sem_pool else {"pool_size": 10, "max_overflow": 20}
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    **_opcoes_pool,
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


@event.listens_for(Session, "after_begin")
def _aplicar_igreja(session, _transaction, connection):
    """A cada transação nova (os routers fazem commit no meio da requisição), diz ao Postgres qual
    é a igreja. `true` = vale só até o fim da transação, então nada vaza entre conexões do pool."""
    igreja_id = session.info.get("igreja_id")
    if igreja_id is not None and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.igreja_id', :v, true)"), {"v": str(igreja_id)})


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: uma sessão por requisição, já presa à igreja do Host (ver main.py)."""
    igreja_id = getattr(request.state, "igreja_id", None)
    session = _async_session_factory()
    session.sync_session.info["igreja_id"] = igreja_id
    token = igreja_atual.set(igreja_id)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
        igreja_atual.reset(token)


@asynccontextmanager
async def sessao_da_igreja(igreja_id: int) -> AsyncGenerator[AsyncSession, None]:
    """Sessão fora de requisição (seed, scripts) presa a uma igreja."""
    session = _async_session_factory()
    session.sync_session.info["igreja_id"] = igreja_id
    token = igreja_atual.set(igreja_id)
    try:
        yield session
    finally:
        await session.close()
        igreja_atual.reset(token)


async def init_db() -> None:
    """Create all tables. Use only for dev / MVP; prefer Alembic for production."""
    from models import Base  # noqa: PLC0415 — deferred to avoid circular import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
