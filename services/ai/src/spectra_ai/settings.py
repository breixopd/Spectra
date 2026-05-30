"""Environment-backed settings for the AI runtime (LLM, embeddings).

Uses the same variable names as ``app.core.config.Settings`` so one .env applies to
both the API process and the standalone AI service image.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    """Subset of platform settings required by ``spectra_ai`` runtime modules."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    TENSORZERO_GATEWAY_URL: str = "http://tensorzero:3000"
    LLM_TIMEOUT: float = 120.0

    # API embeddings by default on the AI image — local fastembed needs AVX2+ (X86_V2).
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: SecretStr = Field(default=SecretStr(""))
    EMBEDDING_API_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_API_KEY: SecretStr = Field(default=SecretStr(""))

    @field_validator("LLM_TIMEOUT")
    @classmethod
    def validate_llm_timeout(cls, v: float) -> float:
        if not 5 <= v <= 1200:
            raise ValueError("LLM_TIMEOUT must be 5-1200 seconds")
        return v

    def embedding_api_key(self) -> str | None:
        """Resolved key for hosted embeddings (EMBEDDING_API_KEY, else OPENAI_API_KEY)."""
        for field in (self.EMBEDDING_API_KEY, self.OPENAI_API_KEY):
            if field and field.get_secret_value():
                return field.get_secret_value()
        return None


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()
