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
    bot_api_key: str = ""

    # AI Provider (OpenAI-compatible API format)
    ai_api_key: str = ""  # OpenRouter / Google AI Studio key
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_model_name: str = "google/gemma-4-26b-a4b-it"  # default model

    # STT Provider (OpenAI-compatible API format — Groq Cloud)
    stt_api_key: str = ""
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model_name: str = "whisper-large-v3"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Создаем синглтон настроек
settings = Settings()
