from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str = Field(default="")
    supabase_anon_key: str = Field(default="")
    supabase_service_key: str = Field(default="")
    # Legacy HS256 shared secret (Project Settings → JWT Keys → legacy secret).
    # Only needed for projects that still sign user tokens symmetrically; projects
    # using asymmetric signing keys are verified via JWKS and need nothing here.
    supabase_jwt_secret: str = Field(default="")
    database_url: str = Field(default="postgresql+psycopg2://postgres:postgres@localhost:5432/postgres")

    # Claude
    anthropic_api_key: str = Field(default="")
    claude_haiku_model: str = Field(default="claude-haiku-4-5")
    claude_sonnet_model: str = Field(default="claude-sonnet-4-6")

    # GitHub
    github_token: str = Field(default="")

    # App
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    scrape_rate_limit: float = 2.0
    max_companies_per_run: int = 50

    # Observability
    sentry_dsn: str = Field(default="")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
