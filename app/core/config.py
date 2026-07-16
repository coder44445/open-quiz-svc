from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

    database_url: str
    redis_url: str

    openai_api_key: str = ""

    max_players: int = 20
    max_topics_per_player: int = 10
    selected_topics_per_game: int = 5
    question_time_limit: int = 60
    
    total_questions: int = Field(default=15, description="Total number of questions to generate per game")
    generation_batch_size: int = Field(default=1, description="Number of questions to generate per LLM call")

    llm_provider: str = "ollama"

    ollama_host: str = "http://localhost:11434"
    
    ollama_model: str = "qwen3:8b"
    
    llm_temperature: float = 0.7
    
    llm_timeout: int = 120

    @model_validator(mode="after")
    def _validate_cors_in_production(self) -> "Settings":
        if self.environment == "production" and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS cannot be '*' in production. "
                "Set it to your actual frontend domain, e.g. https://yourapp.com"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached application settings instance."""

    return Settings()


settings = get_settings()