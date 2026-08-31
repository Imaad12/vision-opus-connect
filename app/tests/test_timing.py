"""Tests for `app.api.timing` -- the per-request phase-timing accumulator
that backs the auth/rbac/db breakdown in AccessLogMiddleware's log line.
"""

from __future__ import annotations

from app.api.timing import get_request_timing, record, start_request_timing, timed


def test_record_before_start_request_timing_is_a_safe_no_op() -> None:
    # No request currently being timed -- must not raise, must not
    # accumulate anywhere observable.
    record("auth", 0.5)
    assert get_request_timing() == {}


def test_record_accumulates_within_one_started_request() -> None:
    start_request_timing()
    record("db", 0.010)
    record("db", 0.020)
    record("auth", 0.005)
    timing = get_request_timing()
    assert timing["db"] == 0.010 + 0.020
    assert timing["auth"] == 0.005


def test_start_request_timing_resets_previous_values() -> None:
    start_request_timing()
    record("db", 0.5)
    start_request_timing()
    assert get_request_timing() == {}


def test_timed_context_manager_records_elapsed_wall_time() -> None:
    start_request_timing()
    with timed("rbac"):
        pass
    timing = get_request_timing()
    assert "rbac" in timing
    assert timing["rbac"] >= 0.0


def test_get_request_timing_returns_a_copy_not_the_live_dict() -> None:
    start_request_timing()
    record("db", 0.1)
    snapshot = get_request_timing()
    snapshot["db"] = 999.0
    assert get_request_timing()["db"] == 0.1
