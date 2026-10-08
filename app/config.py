from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # "../.env" → /app/.env no Docker (WORKDIR=/app/app); ".env" → dev local
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./ebd.db"
    # Sem pool de conexões: só para os testes (vários TestClient = vários loops de eventos)
    db_sem_pool: bool = False
    # Postgres: o app conecta com um papel SEM bypass de RLS (DATABASE_URL, ex.: ebd_app); migrations e
    # provisionamento usam o dono do banco (MIGRATION_DATABASE_URL). Vazio = usa DATABASE_URL.
    migration_database_url: str = ""
    app_db_password: str = ""  # senha do papel do app (scripts/provisionar_papel_app.py)

    # Tenant: domínio base dos subdomínios (igreja.<dominio_base>) e igreja usada quando o Host não
    # é de nenhuma igreja (instalação de uma igreja só e testes). Vazio = host desconhecido dá 404.
    dominio_base: str = ""
    igreja_padrao_id: Optional[int] = None

    # Arquivos enviados (logo da igreja e ícones gerados). Em produção: /data/uploads
    uploads_dir: str = "./uploads"

    # App
    app_name: str = "Sistema EBD"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # Senha do primeiro admin (só usada se o banco estiver sem usuários).
    # Vazia = gera uma senha aleatória e mostra uma única vez no log.
    admin_initial_password: str = ""


settings = Settings()
