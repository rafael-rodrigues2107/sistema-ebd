"""Ajudante dos testes: escolhe o banco (SQLite temporário ou Postgres) e prepara o esquema.

- Sem TEST_DATABASE_URL: SQLite temporário, o app cria as tabelas (como sempre foi).
- Com TEST_DATABASE_URL=postgresql+asyncpg://<dono>:<senha>@host/banco: zera o schema `public`, aplica as
  migrations do Alembic como dono, cria o papel comum do app (ebd_app, sem bypass de RLS) e entrega ao app a
  URL desse papel, então o RLS vale nos testes. O dono (TEST_DATABASE_URL) é usado só para preparar e conferir.
  ATENÇÃO: o schema `public` desse banco é apagado a cada execução. Use um banco de teste.

Os testes rodam o app como instalação de uma igreja só (IGREJA_PADRAO_ID=1), exceto quando o próprio
teste mexe nisso (testes/teste_isolamento.py).
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PG = os.environ.get("TEST_DATABASE_URL", "")  # URL do DONO do banco de teste
SENHA_ADMIN = "admin123"  # só dos testes (ADMIN_INITIAL_PASSWORD)
PAPEL_APP = "ebd_app"
SENHA_APP = "senha_de_teste_do_papel_app_0123456789"  # só dos testes


def _dsn() -> str:
    return PG.replace("postgresql+asyncpg", "postgresql", 1)


def url_app() -> str:
    """URL do papel comum do app (mesmo banco do TEST_DATABASE_URL)."""
    from sqlalchemy.engine import make_url
    return make_url(PG).set(username=PAPEL_APP, password=SENHA_APP).render_as_string(hide_password=False)


def dsn_app() -> str:
    return url_app().replace("postgresql+asyncpg", "postgresql", 1)


def url(db_sqlite: Path) -> str:
    """URL do banco para este teste (e, no Postgres, já deixa esquema e papel do app prontos)."""
    os.environ["IGREJA_PADRAO_ID"] = "1"
    if not PG:
        return f"sqlite+aiosqlite:///{db_sqlite.as_posix()}"
    os.environ["DB_SEM_POOL"] = "true"  # vários TestClient = vários loops; asyncpg não divide conexões entre loops
    import asyncpg

    async def zerar():
        c = await asyncpg.connect(_dsn())
        await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await c.close()

    asyncio.run(zerar())
    env = {**os.environ, "DEBUG": "false", "DATABASE_URL": url_app(), "MIGRATION_DATABASE_URL": PG,
           "APP_DB_PASSWORD": SENHA_APP}
    for cmd in ([sys.executable, "-m", "alembic", "upgrade", "head"],
                [sys.executable, str(RAIZ / "scripts" / "provisionar_papel_app.py")]):
        r = subprocess.run(cmd, cwd=RAIZ, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"{' '.join(cmd[-2:])} falhou:\n{r.stdout}\n{r.stderr}")
    os.environ["MIGRATION_DATABASE_URL"] = PG
    os.environ["APP_DB_PASSWORD"] = SENHA_APP
    return url_app()


def sql(db_sqlite: Path, comando: str, params: tuple = ()) -> None:
    """Executa um comando direto no banco do teste, como DONO (ignora o RLS). Placeholders `?`."""
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
