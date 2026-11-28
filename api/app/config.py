"""Settings, read from environment variables. Every setting is listed in .env.example."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["dev", "oidc"] = "oidc"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    oidc_issuer: str = ""
    oidc_audience: str = ""
    database_url: str = ""
    llm_provider: Literal["stub"] = "stub"  # card M3-02 adds the real provider
    # "local" runs all-MiniLM-L6-v2 on the CPU; "fake" is a deterministic stand-in (card M2-03).
    embedder: Literal["local", "fake"] = "local"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _no_dev_auth_in_production(self) -> "Settings":
        if self.environment == "production" and self.auth_mode == "dev":
            raise ValueError("AUTH_MODE=dev is not allowed when ENVIRONMENT=production")
        if self.environment == "production" and self.embedder == "fake":
            raise ValueError("EMBEDDER=fake is not allowed when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
