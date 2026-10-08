"""Cria/atualiza o papel de banco que o APP usa (sem superusuário e sem bypass de RLS).

Por que existe: o dono do banco (POSTGRES_USER) é superusuário e superusuário ignora o RLS. Se o app
conectasse como dono, o isolamento entre igrejas não valeria. Então o app conecta como um papel
comum (padrão `ebd_app`) com só o necessário: ler/gravar nas tabelas de dados. Migrations, backups
e o provisionamento seguem com o dono.

Roda a cada subida (entrypoint.sh), depois do `alembic upgrade head`; é idempotente.

Variáveis: DATABASE_URL (usuário e senha do papel do app), MIGRATION_DATABASE_URL (dono) e
APP_DB_PASSWORD (a senha do papel; precisa ser igual à da DATABASE_URL).
Sem Postgres, ou se o app usa o mesmo usuário do dono, não faz nada (e avisa).
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from config import settings  # noqa: E402


async def provisionar() -> int:
    app_url = make_url(settings.database_url)
    dono_url = make_url(settings.migration_database_url or settings.database_url)

    if not app_url.get_backend_name().startswith("postgresql"):
        print("provisionar_papel_app: não é Postgres; nada a fazer.")
        return 0
    papel = app_url.username or ""
    if papel == dono_url.username:
        print(f"AVISO: o app conecta com o mesmo usuário do dono ({papel}); o RLS NÃO vale para ele. "
              "Defina MIGRATION_DATABASE_URL (dono) e uma DATABASE_URL com um papel comum.", file=sys.stderr)
        return 0
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", papel):
        raise SystemExit(f"nome de papel inválido: {papel!r}")
    senha = settings.app_db_password
    if not re.fullmatch(r"[A-Za-z0-9_.~-]{16,}", senha):
        raise SystemExit("APP_DB_PASSWORD ausente ou fraca (mínimo 16 caracteres de A-Z a-z 0-9 _ . ~ -).")
    if app_url.password != senha:
        raise SystemExit("APP_DB_PASSWORD diferente da senha da DATABASE_URL.")

    engine = create_async_engine(dono_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as c:
        banco = await c.scalar(text("SELECT current_database()"))
        existe = await c.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname = :p"), {"p": papel})
        acao = "ALTER" if existe else "CREATE"
        # senha e papel foram validados acima (só caracteres seguros), então a interpolação é segura
        await c.execute(text(
            f"{acao} ROLE {papel} LOGIN PASSWORD '{senha}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        ))
        comandos = [
            f'GRANT CONNECT ON DATABASE "{banco}" TO {papel}',
            f"GRANT USAGE ON SCHEMA public TO {papel}",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {papel}",
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {papel}",
            # `igrejas` e o controle de versão das migrations não são do app
            f"REVOKE INSERT, UPDATE, DELETE ON igrejas FROM {papel}",
            f"REVOKE ALL ON alembic_version FROM {papel}",
            # tabelas criadas por migrations futuras já nascem acessíveis ao app
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {papel}",
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {papel}",
        ]
        for cmd in comandos:
            await c.execute(text(cmd))
        info = (await c.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :p"), {"p": papel})).one()
    await engine.dispose()
    if info.rolsuper or info.rolbypassrls:
        raise SystemExit(f"papel {papel} ficou com superusuário/bypassrls; isso anula o isolamento.")
    print(f"papel do app pronto: {papel} (banco {banco}; sem superusuário, sem bypass de RLS)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(provisionar()))
