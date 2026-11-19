"""Settings, read from environment variables. Every setting is listed in .env.example."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["dev", "oidc"] = "oidc"

    oidc_issuer: str = ""
    oidc_audience: str = ""
    database_url: str = ""
    llm_provider: Literal["stub"] = "stub"  # card M3-02 adds the real provider

    @model_validator(mode="after")
    def _no_dev_auth_in_production(self) -> "Settings":
        if self.environment == "production" and self.auth_mode == "dev":
            raise ValueError("AUTH_MODE=dev is not allowed when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
