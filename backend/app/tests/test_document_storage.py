"""Tests for `app.core.document_storage` (P5 of the ingestion-reliability
pass) -- the Supabase Storage client + local-disk-fast-path abstraction
that makes historical-import and client-PO source documents durable
across a Render redeploy.

Uses `httpx.MockTransport` for the Storage-API-call tests (a real fake
HTTP transport, not a mock of this module's own functions) so the actual
request construction -- URL, headers, body -- is exercised, not assumed.
"""

from __future__ import annotations

import httpx
import pytest

from app.core import document_storage
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset_supabase_settings(monkeypatch: pytest.MonkeyPatch):
    # Every test starts from "not configured" (local dev / test default)
    # and opts into a fake-configured state explicitly -- never leaks
    # between tests via shared mutable settings.
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "")
    yield


def test_is_configured_false_by_default():
    assert document_storage.is_configured() is False


def test_is_configured_true_once_both_settings_are_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")
    assert document_storage.is_configured() is True


class TestObjectKeyFor:
    def test_quotation_key_includes_year_batch_and_document_id(self):
        key = document_storage.object_key_for(
            "QUOTATION", year=2018, batch_id=3, document_id=42, suffix="pdf"
        )
        assert key == "quotations/historical/2018/3/42.pdf"

    def test_unbatched_quotation_uses_unbatched_segment(self):
        key = document_storage.object_key_for(
            "QUOTATION", year=2026, batch_id=None, document_id=7, suffix="pdf"
        )
        assert key == "quotations/historical/2026/unbatched/7.pdf"

    def test_client_po_key_has_no_batch_segment(self):
        key = document_storage.object_key_for(
            "PURCHASE_ORDER", year=2026, batch_id=None, document_id=9, suffix="pdf"
        )
        assert key == "client-pos/2026/9.pdf"

    def test_unknown_kind_falls_back_to_other_prefix(self):
        key = document_storage.object_key_for(
            "SOMETHING_NEW", year=2026, batch_id=1, document_id=1, suffix="pdf"
        )
        assert key.startswith("other/2026/")

    def test_suffix_leading_dot_is_normalized(self):
        key = document_storage.object_key_for(
            "PURCHASE_ORDER", year=2026, batch_id=None, document_id=1, suffix=".PDF"
        )
        assert key.endswith(".PDF")
        assert key.count(".") == 1


def test_upload_bytes_is_a_noop_when_not_configured():
    assert document_storage.upload_bytes(b"hello", key="quotations/x.pdf") is None


def test_upload_bytes_calls_the_real_storage_endpoint_with_upsert(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"Key": "vinco-documents/quotations/x.pdf"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = document_storage.upload_bytes(
        b"%PDF-1.4 fake", key="quotations/x.pdf", content_type="application/pdf", http_client=client
    )

    assert result == ("vinco-documents", "quotations/x.pdf")
    assert captured["method"] == "POST"
    assert captured["url"] == "https://proj.supabase.co/storage/v1/object/vinco-documents/quotations/x.pdf"
    assert captured["headers"]["authorization"] == "Bearer secret-key"
    assert captured["headers"]["apikey"] == "secret-key"
    assert captured["headers"]["x-upsert"] == "true"
    assert captured["body"] == b"%PDF-1.4 fake"


def test_upload_bytes_raises_on_a_storage_error_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")

    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="Bucket not found"))
    )
    with pytest.raises(document_storage.DocumentStorageError, match="404"):
        document_storage.upload_bytes(b"data", key="quotations/x.pdf", http_client=client)


def test_download_bytes_returns_the_response_body(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"the bytes")))
    data = document_storage.download_bytes(bucket="vinco-documents", key="quotations/x.pdf", http_client=client)
    assert data == b"the bytes"


def test_ensure_present_is_a_noop_when_the_local_file_already_exists(tmp_path):
    path = tmp_path / "already-here.pdf"
    path.write_bytes(b"local copy")

    result = document_storage.ensure_present(
        original_path=str(path), storage_bucket="vinco-documents", storage_key="quotations/x.pdf"
    )

    assert result == path
    assert path.read_bytes() == b"local copy"  # untouched, never re-downloaded


def test_ensure_present_is_a_noop_when_no_durable_copy_was_ever_recorded(tmp_path):
    missing_path = tmp_path / "never-existed.pdf"
    result = document_storage.ensure_present(
        original_path=str(missing_path), storage_bucket=None, storage_key=None
    )
    # Falls through to exactly today's "file not found" handling --
    # never invents a file, never raises here.
    assert result == missing_path
    assert not missing_path.exists()


def test_ensure_present_redownloads_a_missing_local_file_from_durable_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")

    missing_path = tmp_path / "restored" / "document.pdf"  # parent dir doesn't exist yet either
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"restored bytes"))
    )

    result = document_storage.ensure_present(
        original_path=str(missing_path),
        storage_bucket="vinco-documents",
        storage_key="quotations/x.pdf",
        http_client=client,
    )

    assert result == missing_path
    assert missing_path.read_bytes() == b"restored bytes"


def test_ensure_present_swallows_a_download_failure_and_returns_the_original_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """A redeploy that wiped local disk AND a Supabase Storage outage at
    the same moment must not turn into a 500 -- the caller (`run_extraction`
    /the preview routes) already has a well-defined "file not found" path
    that this must fall back to."""
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "secret-key")

    missing_path = tmp_path / "document.pdf"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")))

    result = document_storage.ensure_present(
        original_path=str(missing_path),
        storage_bucket="vinco-documents",
        storage_key="quotations/x.pdf",
        http_client=client,
    )

    assert result == missing_path
    assert not missing_path.exists()
