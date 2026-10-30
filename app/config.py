"""Typed runtime configuration, loaded from environment / .env.

Using pydantic-settings keeps config in one place and validated, and pairs
with the committed .env.example (placeholder names only — no secrets).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="TRIAGE_", extra="ignore"
    )

    app_name: str = "Customer Support Ticket Triage System"
    version: str = "1.0.0"

    # Below this model confidence, a ticket is sent to the human-review queue
    # instead of being auto-assigned. This is the core "exception path".
    confidence_threshold: float = 0.45

    # Optional shared-secret auth for the write endpoints. Unset = open (no auth).
    api_key: str | None = None

    # Artifact + data locations (absolute, derived from repo root).
    db_path: str = str(BASE_DIR / "data" / "triage.db")
    model_path: str = str(BASE_DIR / "data" / "model.joblib")
    data_csv: str = str(BASE_DIR / "data" / "tickets.csv")

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so config is parsed once per process."""
    return Settings()
