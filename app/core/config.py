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

    #: Browser origins allowed to call this API cross-origin (the frontend
    #: dev server and, in production, the deployed web app's real domain).
    #: Comma-separated in the environment, e.g.
    #: VISION_CORS_ALLOWED_ORIGINS="https://app.example.com,https://staging.example.com".
    #: Defaults cover Vite's common local ports so a fresh checkout works
    #: without any configuration -- without this, every cross-origin
    #: request from the frontend fails browser CORS preflight (a 405 on
    #: OPTIONS, no Access-Control-Allow-Origin header at all), which
    #: surfaces to the user as a generic "Failed to fetch" with no
    #: indication of why.
    cors_allowed_origins: str = (
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
