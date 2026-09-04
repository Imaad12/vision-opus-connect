"""Durable document storage (P5 of the ingestion-reliability pass):
Supabase Storage as the source of truth for original historical-import
and client-PO source files, with a transparent local-disk fast-path.

Why this exists: `settings.imports_storage_dir` (Render's own disk)
does NOT survive a redeploy or restart -- every file written there is
gone the moment the process is replaced, which is exactly what made a
previously-uploaded document's OCR re-attempt (or even its page-preview)
silently 404 after any deploy. Supabase Storage is already part of
VINCO's stack (the same project this backend already authenticates
against for Auth/RBAC -- see `app.core.config.Settings.supabase_url`/
`supabase_service_role_key`), so it is the fix here rather than a new
dependency: every new upload is written there too, keyed by
`ImportedDocument.id`, and `ensure_present` below transparently
re-downloads a document's bytes back to its expected local path whenever
that path has gone missing -- so every EXISTING caller that already
opens `Path(document.original_path)` directly (`import_service.
run_extraction`, the page-preview routes) keeps working completely
unmodified; the only change is that they stop observing a missing file
once storage is actually configured.

Local-only fallback (Supabase Storage env vars unset -- local dev, the
test suite, or a deploy not yet configured) preserves today's exact
behavior: `is_configured()` is False, every write/read here becomes a
no-op, and a document is only ever on local disk -- unchanged from
before this module existed, including its known ephemeral-disk
limitation in that configuration (still true, and still worth closing by
setting the Supabase env vars in production).

Never touches an existing file on disk uninvited, and never deletes
anything -- see `scripts/migrate_documents_to_storage.py` for the
explicit, opt-in, one-file-at-a-time migration path for documents that
were uploaded before this module existed (P5's "provide a controlled
migration path", never an automatic one).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger("app.storage")

__all__ = [
    "DEFAULT_BUCKET",
    "DocumentStorageError",
    "is_configured",
    "object_key_for",
    "upload_bytes",
    "download_bytes",
    "ensure_present",
]

#: A single private bucket for every source document VINCO's import
#: pipelines produce (historical quotations, client POs, and -- per this
#: feature's own report -- future invoice/contract source documents),
#: distinguished from each other by their object key prefix
#: (`object_key_for` below), not by separate buckets. Must be created as
#: a PRIVATE bucket in the Supabase dashboard before this is used in
#: production -- this module never assumes it exists and always surfaces
#: a clear `DocumentStorageError` if it doesn't, rather than silently
#: losing the upload.
DEFAULT_BUCKET = "vinco-documents"


class DocumentStorageError(Exception):
    """A Supabase Storage call failed outright (network/auth/missing
    bucket/...) -- distinct from "file not found", which every existing
    caller already handles as a normal, reviewable document outcome."""


def is_configured() -> bool:
    """Whether Supabase Storage can actually be used right now -- the
    same two settings `SupabaseAdmin` (app/api/auth.py) already requires
    for user-management, reused here rather than a new pair of env vars."""
    return bool(settings.supabase_url and settings.supabase_service_role_key)


#: `ImportDocumentKind` value -> object-key prefix, per this feature's
#: own report's suggested layout. `str` keys (not the enum itself) so
#: this module has no import-time dependency on `app.core.enums` /
#: `app.models` -- callers pass whatever kind string they already have.
_KIND_PREFIXES: dict[str, str] = {
    "QUOTATION": "quotations/historical",
    "BOQ": "quotations/historical",
    "PURCHASE_ORDER": "client-pos",
}


def object_key_for(
    document_kind: str,
    *,
    year: int,
    batch_id: int | None,
    document_id: int,
    suffix: str,
) -> str:
    """Builds a stable, human-traceable object key -- `document_id` (an
    `ImportedDocument`/`ClientAwardEvidence`-document id, never a random
    uuid) makes every key trivially traceable back to its owning row and
    collision-proof by construction, since that id is never reused."""
    prefix = _KIND_PREFIXES.get(document_kind, "other")
    ext = f".{suffix.lstrip('.')}" if suffix else ""
    if prefix == "client-pos":
        return f"{prefix}/{year}/{document_id}{ext}"
    batch_segment = str(batch_id) if batch_id is not None else "unbatched"
    return f"{prefix}/{year}/{batch_segment}/{document_id}{ext}"


def _headers() -> dict[str, str]:
    key = settings.supabase_service_role_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _object_url(bucket: str, key: str) -> str:
    return f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{key}"


def upload_bytes(
    data: bytes,
    *,
    key: str,
    content_type: str = "application/octet-stream",
    bucket: str = DEFAULT_BUCKET,
    http_client: httpx.Client | None = None,
) -> tuple[str, str] | None:
    """Uploads `data` to Supabase Storage at `bucket`/`key`, overwriting
    any existing object at that exact key (`x-upsert`) -- safe because
    every key this module generates already embeds the owning row's id,
    so re-uploading the same key only ever happens for the same
    document. Returns `(bucket, key)` on success, or `None` when storage
    isn't configured at all (the caller's local-disk write remains the
    only copy -- exactly today's behavior). Raises `DocumentStorageError`
    on a genuine failure; callers decide whether that should block their
    own request (see each call site's own comment)."""
    if not is_configured():
        return None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        response = client.request(
            "POST",
            _object_url(bucket, key),
            content=data,
            headers={**_headers(), "Content-Type": content_type, "x-upsert": "true"},
        )
    except httpx.HTTPError as exc:
        raise DocumentStorageError(f"Could not reach Supabase Storage to upload {bucket}/{key}: {exc}") from exc
    finally:
        if http_client is None:
            client.close()
    if response.status_code >= 400:
        raise DocumentStorageError(
            f"Supabase Storage upload of {bucket}/{key} failed ({response.status_code}): "
            f"{response.text[:300]}"
        )
    return bucket, key


def download_bytes(*, bucket: str, key: str, http_client: httpx.Client | None = None) -> bytes:
    """Fetches one object's raw bytes. Raises `DocumentStorageError` on
    any non-2xx response or network failure -- there is no "file not
    found, return empty" fallback here; a caller that wants that
    tolerance (see `ensure_present`) catches it explicitly."""
    client = http_client or httpx.Client(timeout=30.0)
    try:
        response = client.request("GET", _object_url(bucket, key), headers=_headers())
    except httpx.HTTPError as exc:
        raise DocumentStorageError(f"Could not reach Supabase Storage to download {bucket}/{key}: {exc}") from exc
    finally:
        if http_client is None:
            client.close()
    if response.status_code >= 400:
        raise DocumentStorageError(
            f"Supabase Storage download of {bucket}/{key} failed ({response.status_code}): "
            f"{response.text[:300]}"
        )
    return response.content


def ensure_present(
    *,
    original_path: str,
    storage_bucket: str | None,
    storage_key: str | None,
    http_client: httpx.Client | None = None,
) -> Path:
    """Guarantees `Path(original_path)` exists on THIS process's local
    disk before returning it, re-downloading from Supabase Storage if
    it's missing -- a redeploy wiped the ephemeral disk, or this is a
    fresh worker instance that never had it -- and a durable copy is on
    record (`storage_bucket`/`storage_key` both set). A no-op, returning
    the path unchanged, whenever the file is already there (the
    overwhelmingly common case: same process that wrote it, no redeploy
    in between) or no durable copy was ever recorded for this document
    (falls through to exactly today's "file not found" handling in
    `run_extraction`/the preview routes, unchanged). A download failure
    is logged and swallowed, not raised -- callers already have a
    well-defined "the file isn't there" path (a FAILED extraction status,
    a 404 from the preview route) that this must fall back to, not a new
    hard failure mode of its own."""
    path = Path(original_path)
    if path.exists():
        return path
    if not storage_bucket or not storage_key:
        return path
    try:
        data = download_bytes(bucket=storage_bucket, key=storage_key, http_client=http_client)
    except DocumentStorageError:
        logger.exception(
            "Could not restore %s from durable storage (%s/%s)", original_path, storage_bucket, storage_key
        )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
