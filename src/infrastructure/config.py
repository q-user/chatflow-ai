from pydantic_settings import BaseSettings, SettingsConfigDict

# Single source of truth for all supported module types.
# Used by entitlements logic, migrations, and future admin UI.
ALL_MODULE_TYPES: list[str] = ["finance", "estimator", "hr"]


class Settings(BaseSettings):
    # Pydantic автоматически сопоставит имена из .env (регистр не важен)
    app_name: str = "ChatFlow AI"
    environment: str = "development"
    debug: bool = False
    domain: str = "localhost"

    database_url: str = ""
    database_sync_url: str = ""
    redis_url: str = ""

    # Ресурсные лимиты
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 3
    log_level: str = "INFO"

    secret_key: str = ""
    bot_api_key: str = ""

    # HTTP proxy (used by Telegram adapter only; MX/Yandex go direct)
    http_proxy: str | None = None

    # AI Provider (OpenAI-compatible API format)
    ai_api_key: str = ""  # OpenRouter / NVIDIA / Google AI Studio key
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_model_name: str = "google/gemma-4-26b-a4b-it"  # default model
    ai_timeout: float = 600.0  # NVIDIA free tier can take up to 10 min

    # STT Provider selection: "groq" or "riva"
    stt_provider: str = "groq"

    # STT — Groq Cloud (OpenAI-compatible API)
    stt_api_key: str = ""
    stt_base_url: str = "https://api.groq.com/openai/v1"
    stt_model_name: str = "whisper-large-v3"

    # STT — NVIDIA Riva (gRPC)
    nvidia_api_key: str = ""
    riva_server_url: str = "dns:///grpc.nvcf.nvidia.com:443"
    riva_function_id: str = "b0e8b4a5-217c-40b7-9b96-17d84e666317"

    # Sentry
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.1

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Создаем синглтон настроек
settings = Settings()
