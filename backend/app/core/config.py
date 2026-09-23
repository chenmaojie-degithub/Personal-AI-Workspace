from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # CORS
    cors_origins: str = "http://localhost:5173"

    # LLM provider
    llm_provider: str = "deepseek"
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openrouter/free"

    # Legacy OpenAI-compatible chat settings. Kept so existing .env files work.
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"

    # Embeddings are configured separately so a compatible chat provider
    # (for example DeepSeek) is never used for OpenAI-only embedding models.
    embedding_provider: str = "local"
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    local_embedding_cache_dir: str = "./models"
    openai_embedding_api_key: str | None = None
    openai_embedding_base_url: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"

    # Application database. DATABASE_PATH remains as a compatibility fallback
    # for existing local .env files; new configuration should use DATABASE_URL.
    database_url: str | None = None
    database_path: str = "./data/ai_chat.sqlite3"
    postgres_target_password: str | None = None

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{Path(self.database_path).as_posix()}"

    # File storage / RAG (independent from the application database)
    storage_dir: str = "./storage"
    chroma_persist_dir: str = "./chroma"
    chroma_collection: str = "rag_chunks"


settings = Settings()
