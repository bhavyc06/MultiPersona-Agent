from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Claude API
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/consulting_sim"

    @property
    def postgres_conn_string(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    redis_url: str = "redis://localhost:6379/0"
    chroma_persist_dir: str = "./data/chroma"

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Session limits
    session_max_turns: int = 12
    session_timeout_seconds: int = 240
    session_token_budget: int = 150000

    # Model IDs
    model_opus: str = "claude-opus-4-5"
    model_sonnet: str = "claude-sonnet-4-5"
    model_haiku: str = "claude-haiku-4-5-20251001"

    # Observability
    logfire_token: str = ""
    environment: str = "development"

    # Memory encryption
    memory_encryption_key: str = ""

    # Clarification loop
    clarification_max_rounds: int = 3
    clarification_answer_timeout_seconds: int = 300

    # Adapter selection: True → ClaudeAdapter (CLI subprocess), False → ApiClaudeAdapter (SDK)
    use_cli: bool = True


settings = Settings()
