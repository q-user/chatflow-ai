from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Pydantic автоматически сопоставит имена из .env (регистр не важен)
    app_name: str = "ChatFlow AI"
    environment: str = "development"
    debug: bool = False

    database_url: str = ""
    database_sync_url: str = ""
    redis_url: str = ""

    # Ресурсные лимиты
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 3
    log_level: str = "INFO"

    secret_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Создаем синглтон настроек
settings = Settings()
