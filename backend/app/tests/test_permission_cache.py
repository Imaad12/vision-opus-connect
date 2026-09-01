"""Tests for `app.api.permission_cache` -- TTL expiry, per-key isolation,
and the disable switch. See that module's docstring for the full
TTL/revocation/multi-user-isolation/process-behavior/security writeup;
this file verifies the mechanics it describes actually hold.
"""

from __future__ import annotations

from app.api.permission_cache import (
    clear_permission_cache,
    get_cached_permission,
    set_cached_permission,
)
from app.core.config import settings


def test_uncached_permission_returns_none() -> None:
    assert get_cached_permission("user-a", "customers.view") is None


def test_set_then_get_returns_the_cached_value(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 60.0)
    set_cached_permission("user-a", "customers.view", True)
    assert get_cached_permission("user-a", "customers.view") is True

    set_cached_permission("user-b", "customers.view", False)
    assert get_cached_permission("user-b", "customers.view") is False


def test_different_users_never_share_a_cache_entry(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 60.0)
    set_cached_permission("user-a", "customers.create", True)
    # A different user, same permission string, must not see user-a's entry.
    assert get_cached_permission("user-b", "customers.create") is None


def test_different_permissions_for_the_same_user_are_independent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 60.0)
    set_cached_permission("user-a", "customers.view", True)
    assert get_cached_permission("user-a", "customers.create") is None


def test_entry_expires_after_the_configured_ttl(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 60.0)
    set_cached_permission("user-a", "customers.view", True)

    # Simulate time passing without a real sleep: monkeypatch this
    # module's own `time.monotonic` so "now" is 61s later than whatever
    # `set_cached_permission` recorded as the expiry basis.
    import time as time_module

    import app.api.permission_cache as cache_module

    real_monotonic = time_module.monotonic
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: real_monotonic() + 61.0)
    assert get_cached_permission("user-a", "customers.view") is None


def test_ttl_zero_disables_caching_entirely(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 0)
    set_cached_permission("user-a", "customers.view", True)
    assert get_cached_permission("user-a", "customers.view") is None


def test_clear_permission_cache_drops_everything(monkeypatch) -> None:
    monkeypatch.setattr(settings, "permission_cache_ttl_seconds", 60.0)
    set_cached_permission("user-a", "customers.view", True)
    clear_permission_cache()
    assert get_cached_permission("user-a", "customers.view") is None
