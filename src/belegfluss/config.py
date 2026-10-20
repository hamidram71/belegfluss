"""Runtime configuration, read from environment variables and an optional ``.env`` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELEGFLUSS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "local"
    storage_dir: Path = Path("var/documents")
    max_upload_mb: int = 20
    master_data_dir: Path = Path("data/synthetic/master_data")
    contracts_dir: Path = Path("data/synthetic/contracts")
    # ERP export of purchase orders (one purchase_order.json per order, searched recursively).
    erp_orders_dir: Path = Path("data/synthetic/sets")
    matches_dir: Path = Path("var/matches")

    # Contract index (ADR 0007). Without a database URL an in-memory index is used.
    database_url: str | None = None
    # No model means the offline hashing embedder: a lexical baseline, no API calls.
    embedding_model: str | None = None
    embedding_dimensions: int = 512
    # "auto": the LLM adjudicator if an LLM is configured, otherwise the deterministic one.
    adjudicator: Literal["auto", "llm", "deterministic"] = "auto"

    # LLM, used only for documents without structured data (ADR 0001, ADR 0005).
    # No default model on purpose: model ids change; the operator chooses one explicitly.
    llm_provider: Literal["openai", "azure"] = "openai"
    llm_model: str | None = None
    llm_image_detail: Literal["low", "high", "auto"] = "high"

    # Standard SDK variable names, so the keys work exactly as in OpenAI's documentation.
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key")
    )
    azure_openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AZURE_OPENAI_API_KEY", "azure_openai_api_key"),
    )
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
