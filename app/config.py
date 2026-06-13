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

    # App
    app_name: str = "Sistema EBD"
    debug: bool = True
    secret_key: str = "change-me-in-production"


settings = Settings()
