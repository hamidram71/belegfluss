"""Runtime configuration, read from environment variables prefixed with ``BELEGFLUSS_``."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELEGFLUSS_", env_file=".env", extra="ignore")

    environment: str = "local"
    storage_dir: Path = Path("var/documents")
    max_upload_mb: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
