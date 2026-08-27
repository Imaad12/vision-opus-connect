"""Application settings.

A single place to resolve configuration (database location, and the API
layer's identity/permission provider) from environment variables, with a
sensible default for local development. Nothing else in the codebase
should read `os.environ` directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    database_path: Path = PROJECT_ROOT / "vision_contracting.db"

    #: Identity/RBAC currently lives in the existing Supabase project the
    #: VINCO frontend already authenticates against (see API_ARCHITECTURE.md
    #: -- this backend deliberately does not duplicate the role/permission
    #: model). Empty by default so the API layer fails closed, loudly, if
    #: these are never configured, rather than silently trusting nothing.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_audience: str = "authenticated"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
