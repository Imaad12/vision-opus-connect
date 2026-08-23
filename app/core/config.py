"""Application settings.

A single place to resolve configuration (currently just the database
location) from environment variables, with a sensible default for local
development. Nothing else in the codebase should read `os.environ`
directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    database_path: Path = PROJECT_ROOT / "vision_contracting.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
