"""Centralized configuration. All env vars flow through here."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Runtime
    app_env: str = "dev"
    log_level: str = "INFO"
    sentry_dsn: str | None = None

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://realitni:realitni_dev_password@postgres:5432/realitni"
    )

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # S3 / MinIO
    s3_endpoint_url: str | None = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_raw: str = "raw-listings"
    s3_bucket_photos: str = "listing-photos"
    s3_region: str = "us-east-1"

    # Scraper
    scraper_user_agent: str = "RealitniSkener/0.1 (+contact@example.cz)"
    sreality_rate_limit_rps: float = 1.0
    sreality_base_url: str = "https://www.sreality.cz"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
