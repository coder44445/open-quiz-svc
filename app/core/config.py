from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Quiz Engine")
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str
    redis_url: str

    openai_api_key: str = ""

    max_players: int = 20
    max_topics_per_player: int = 10
    selected_topics_per_game: int = 5
    question_time_limit: int = 60

    llm_provider: str = "ollama"

    ollama_host: str = "http://localhost:11434"
    
    ollama_model: str = "qwen3:8b"
    
    llm_temperature: float = 0.7
    
    llm_timeout: int = 120


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached application settings instance."""

    return Settings()


settings = get_settings()