"""Bulk historical-quotation ingestion for a local folder of PDFs.

The browser "Choose Files" flow (`POST /imports/batches/{id}/documents`,
`app.api.routers.imports.upload_batch_documents`) is right for a handful
of files at a time. It is not a usable interface for a company archive of
10,000-50,000 historical quotation PDFs -- nobody should have to
multi-select thousands of files in a Finder dialog, and a single HTTP
request carrying that many files is not something a browser or FastAPI is
built to do.

This does NOT introduce a second ingestion path. It calls the exact same
staging/dedup/enqueue primitives the web upload route already calls --
`import_service.compute_file_hash`, `import_service.find_existing_by_hash`,
`import_service.stage_document_for_queue`, `import_service.
is_resumable_extraction_status`, `document_storage.upload_bytes`,
`import_queue_service.enqueue_import_job` -- so a file queued this way is
indistinguishable, from the worker's point of view, from one queued
through the web UI. All this module adds is: walk a directory tree
instead of reading `UploadFile`s, and print a summary instead of
returning JSON. Extraction/OCR itself is completely untouched -- a
worker (`app/worker.py`) claims the `ImportJob` this creates and calls
`import_service.run_extraction` exactly as for a web upload; this
command's job is done the moment a file is durably stored and queued.

Usage (recursively discovers every *.pdf under the given folder):

    python -m app.cli.bulk_import /path/to/quotation-archive --batch-label "2018 archive"

or, once this package is installed (`pip install -e .`):

    vinco-import /path/to/quotation-archive --batch-label "2018 archive"

Resumable by construction, not by any state this command keeps of its
own: every file is identified by its own SHA-256
(`import_service.compute_file_hash`) against `ImportedDocument.file_hash`
-- the same hash-based duplicate detection the web upload route already
relies on -- so stopping this command (Ctrl-C, a crash, a reboot) and
re-running it against the same folder recognizes every already-staged
file and skips it (or, if it was left mid-pipeline, re-queues it) rather
than re-importing it. `import_queue_service.enqueue_import_job` is
itself idempotent per document (a unique constraint on
`imported_document_id`), so this can never create two queued jobs for
one file even across an interrupted run.

Durable storage (Supabase Storage) is REQUIRED for this command, unlike
the web upload route, which degrades gracefully to local-disk-only for
local development. A bulk run that silently left thousands of originals
depending only on Render's ephemeral local disk would defeat the entire
point of durable storage -- this refuses to start at all if
`document_storage.is_configured()` is False, and refuses to enqueue any
individual document whose upload to Storage failed (reported as a
failure to retry, never silently treated as safely archived).

Processes one file at a time and commits to the database in bounded
chunks (`--commit-every`, default 200) -- never discovers the full file
list before starting, and never holds more than one file's bytes in
memory at once, so this is safe to run against an archive of any size.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import document_storage
from app.database.session import session_scope
from app.models.import_staging import ImportedDocument
from app.services import import_queue_service, import_service
from app.services.errors import ValidationError

_PDF_SUFFIXES = {".pdf"}


@dataclass
class BulkImportReport:
    found: int = 0
    already_imported: int = 0
    new: int = 0
    resumed: int = 0
    queued: int = 0
    failed_storage: int = 0
    failed_read: int = 0

    def print_summary(self) -> None:
        print(f"Found: {self.found}")
        print(f"Already imported: {self.already_imported}")
        print(f"New: {self.new}")
        print(f"Resumed: {self.resumed}")
        print(f"Queued: {self.queued}")
        print(f"Failed (durable storage): {self.failed_storage}")
        print(f"Failed (unreadable file): {self.failed_read}")


def discover_pdfs(root: Path) -> Iterator[Path]:
    """Yields every `*.pdf` under `root`, recursively, one path at a
    time -- `Path.rglob` walks the tree lazily, so this never
    materializes a full file list for an archive of any size."""
    for entry in root.rglob("*"):
        if entry.is_file() and entry.suffix.lower() in _PDF_SUFFIXES:
            yield entry


def _relative_source_path(root: Path, path: Path) -> str:
    """Provenance for `ImportedDocument.notes` (see this module's own
    docstring: no new database column exists for this, and none is
    added here -- the original filename alone is not enough to trace a
    document back to where it lived in the archive, e.g.
    `2018/Riyadh/QTN-104.pdf`, so the path relative to the scanned root
    is recorded as free text instead)."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def process_one_file(
    session: Session,
    path: Path,
    *,
    root: Path,
    batch_id: int,
    report: BulkImportReport,
) -> None:
    """Stages (or resumes) and enqueues exactly one file, mirroring
    `app.api.routers.imports.upload_batch_documents`'s own per-file
    logic. Never raises for an ordinary per-file problem (an unreadable
    file, a Storage upload failure) -- those are recorded on `report`
    and the caller moves on to the next file, exactly like one bad
    document in a browser multi-upload doesn't abort the rest."""
    report.found += 1
    try:
        file_hash = import_service.compute_file_hash(path)
    except OSError as exc:
        report.failed_read += 1
        print(f"  SKIP (unreadable): {path} -- {exc}")
        return

    is_new = False
    document = import_service.find_existing_by_hash(session, file_hash)
    if document is None:
        try:
            document = import_service.stage_document_for_queue(
                session, path, original_filename=path.name, batch_id=batch_id
            )
        except ValidationError:
            # A concurrent bulk-import run (or the web UI) staged the
            # identical hash between our check above and here --
            # vanishingly rare, handled the same as finding it the
            # first time rather than aborting this file.
            document = import_service.find_existing_by_hash(session, file_hash)
            if document is None:
                raise
        else:
            document.notes = f"Bulk import source: {_relative_source_path(root, path)}"
            session.flush()
            is_new = True

    if not is_new and not import_service.is_resumable_extraction_status(document.extraction_status):
        report.already_imported += 1
        return

    if document.storage_bucket is None and document_storage.is_configured():
        try:
            data = path.read_bytes()
        except OSError as exc:
            report.failed_read += 1
            print(f"  SKIP (unreadable): {path} -- {exc}")
            return
        try:
            key = document_storage.object_key_for(
                "QUOTATION",
                year=document.created_at.year if document.created_at else date.today().year,
                batch_id=batch_id,
                document_id=document.id,
                suffix=document.extension,
            )
            result = document_storage.upload_bytes(data, key=key, content_type="application/pdf")
        except document_storage.DocumentStorageError as exc:
            # Per this module's own docstring: never enqueue a document
            # as though it were safely archived when the upload that was
            # supposed to archive it just failed.
            report.failed_storage += 1
            print(f"  FAILED (durable storage): {path} -- {exc}")
            return
        if result is not None:
            document.storage_bucket, document.storage_key = result
            session.flush()

    import_queue_service.enqueue_import_job(session, document)
    if is_new:
        report.new += 1
    else:
        report.resumed += 1
    report.queued += 1


def run_bulk_import(
    root: Path,
    *,
    batch_label: str | None,
    batch_id: int | None,
    commit_every: int,
) -> BulkImportReport:
    if not document_storage.is_configured():
        raise SystemExit(
            "Durable storage is not configured (VISION_SUPABASE_URL / "
            "VISION_SUPABASE_SERVICE_ROLE_KEY are not set). Bulk import "
            "refuses to run without it -- production originals must not "
            "end up depending on this command's own local disk. Configure "
            "Supabase Storage first, then re-run."
        )

    report = BulkImportReport()

    with session_scope() as session:
        if batch_id is not None:
            batch = import_service.get_import_batch(session, batch_id)
            if batch is None:
                raise SystemExit(f"Batch {batch_id} not found.")
        else:
            batch = import_service.create_import_batch(session, label=batch_label)
            print(f"Created batch #{batch.id}: {batch.label!r}")
        resolved_batch_id = batch.id

    processed_since_commit = 0
    with session_scope() as session:
        try:
            for path in discover_pdfs(root):
                process_one_file(session, path, root=root, batch_id=resolved_batch_id, report=report)
                processed_since_commit += 1
                if processed_since_commit >= commit_every:
                    session.commit()
                    session.expunge_all()  # bound memory -- don't keep every processed row's identity map entry
                    processed_since_commit = 0
                    print(f"  ... {report.found} found so far")
        except KeyboardInterrupt:
            print("\nInterrupted -- committing what's queued so far. Safe to re-run: "
                  "already-queued files are recognized by hash and skipped.")
            session.commit()
            raise

    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vinco-import",
        description="Recursively discover PDFs under a folder and queue each one for historical-quotation ingestion.",
    )
    parser.add_argument("source_dir", type=Path, help="Folder to scan recursively for PDFs.")
    batch_group = parser.add_mutually_exclusive_group()
    batch_group.add_argument("--batch-label", help="Create a new batch with this label.")
    batch_group.add_argument("--batch-id", type=int, help="Add to an existing batch instead of creating a new one.")
    parser.add_argument(
        "--commit-every",
        type=int,
        default=200,
        help=(
            "Commit to the database after this many files (default: 200) -- bounds how much "
            "work an interruption mid-run can leave uncommitted, without committing once per file."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root: Path = args.source_dir
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    try:
        report = run_bulk_import(
            root, batch_label=args.batch_label, batch_id=args.batch_id, commit_every=args.commit_every
        )
    except KeyboardInterrupt:
        return 130

    report.print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
