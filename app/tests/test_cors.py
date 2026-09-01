"""Regression test for the CORS gap that made every cross-origin frontend
request fail with a bare "Failed to fetch" (a 405 on OPTIONS preflight,
no Access-Control-Allow-Origin header at all, from a missing
`CORSMiddleware` -- see `app/api/main.py` and `app/core/config.py`).

Deliberately hits the real `app.api.main.app` with no dependency
overrides: CORS preflight is handled by middleware before any route or
auth dependency runs, so this must work even for an unauthenticated,
unconfigured request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app

ALLOWED_ORIGIN = "http://localhost:8080"


def test_preflight_from_allowed_origin_succeeds():
    with TestClient(app) as client:
        response = client.options(
            "/clients",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_real_response_carries_cors_header_for_allowed_origin():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_disallowed_origin_gets_no_cors_header():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://not-allowed.example.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


# Regression for the VINCO desktop (Tauri) build's Customers page failing
# with a bare network-level error (no HTTP status -- the signature of a
# blocked CORS preflight) even after the frontend's API URL, auth, and
# role were all confirmed correct. Root cause: the desktop webview's fixed
# `Origin` (`tauri://localhost` on macOS/Linux, `https://tauri.localhost`
# on Windows) was never in `VISION_CORS_ALLOWED_ORIGINS` on Render --
# nobody configuring "the frontend's origin" would think to add a
# non-`https://<domain>` value there. `app/core/config.py`'s
# `cors_allowed_origins_list` now always includes both, independent of
# whatever the env var is set to, so this can't regress even if the env
# var is later edited to list only the web app's domain again.
@pytest.mark.parametrize("desktop_origin", ["tauri://localhost", "https://tauri.localhost"])
def test_desktop_app_origin_always_allowed_regardless_of_env_config(desktop_origin: str):
    with TestClient(app) as client:
        response = client.options(
            "/clients",
            headers={
                "Origin": desktop_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == desktop_origin
