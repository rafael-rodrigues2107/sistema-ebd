"""Ajudante dos testes: escolhe o banco (SQLite temporário ou Postgres) e prepara o esquema.

- Sem TEST_DATABASE_URL: SQLite temporário, o app cria as tabelas (como sempre foi).
- Com TEST_DATABASE_URL=postgresql+asyncpg://...: zera o schema `public`, aplica as
  migrations do Alembic (valida a migration junto) e roda os testes nesse banco.
  ATENÇÃO: o schema `public` desse banco é apagado a cada execução. Use um banco de teste.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PG = os.environ.get("TEST_DATABASE_URL", "")
SENHA_ADMIN = "admin123"  # só dos testes (ADMIN_INITIAL_PASSWORD)


def _dsn() -> str:
    return PG.replace("postgresql+asyncpg", "postgresql", 1)


def url(db_sqlite: Path) -> str:
    """URL do banco para este teste (e, no Postgres, já deixa o esquema pronto)."""
    if not PG:
        return f"sqlite+aiosqlite:///{db_sqlite.as_posix()}"
    os.environ["DB_SEM_POOL"] = "true"  # vários TestClient = vários loops; asyncpg não divide conexões entre loops
    import asyncpg

    async def zerar():
        c = await asyncpg.connect(_dsn())
        await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await c.close()

    asyncio.run(zerar())
    env = {**os.environ, "DATABASE_URL": PG, "DEBUG": "false"}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RAIZ, env=env,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("alembic falhou:\n" + r.stderr)
    return PG


def sql(db_sqlite: Path, comando: str, params: tuple = ()) -> None:
    """Executa um comando direto no banco do teste (placeholders `?`)."""
    if not PG:
        import sqlite3
        con = sqlite3.connect(db_sqlite)
        con.execute(comando, params)
        con.commit()
        con.close()
        return
    import asyncpg
    n = iter(range(1, 100))
    pg_cmd = "".join(f"${next(n)}" if ch == "?" else ch for ch in comando)

    async def rodar():
        c = await asyncpg.connect(_dsn())
        await c.execute(pg_cmd, *params)
        await c.close()

    asyncio.run(rodar())
