"""Durable, database-backed ingestion queue (P2/P3 of the production-
reliability pass -- see this feature's own report).

This is the concrete replacement for `BackgroundTasks.add_task` as the
thing that actually runs `import_service.run_extraction`. The previous
design ran extraction as a coroutine living only in the web process's
own memory for the lifetime of one background task -- a Render web-
service restart (a deploy, a crash, a scale event) silently discarded
whatever was mid-run, leaving the document's `extraction_status` stuck
at PENDING/EXTRACTING forever with nothing anywhere that would ever
resume it, and nothing telling the frontend that had happened either
(it just kept polling a document that would never change). An
`ImportJob` row is real, committed database state: it exists whether or
not any worker process happens to be running right now, and a new
worker (the same one restarted, or a second instance) simply picks up
whatever the table says is still outstanding.

Claim/complete/fail are three separate, short transactions -- NOT one
long one held for the duration of processing a document. Claiming marks
a row PROCESSING and commits immediately (releasing any row lock used to
make the claim itself concurrency-safe); the actual, potentially slow
`run_extraction` call happens afterward, in a separate session, so a
multi-minute OCR pass never holds a database lock or a pooled connection
the whole time. This module's own functions never call `run_extraction`
themselves -- see `process_import_job` for the one function that
sequences "claim, then process, then complete/fail", and `app/worker.py`
for the loop that calls it repeatedly.

Concurrency safety: `claim_next_import_job` uses `SELECT ... FOR UPDATE
SKIP LOCKED` on PostgreSQL (the real production database) so two workers
racing for the same job never both get it -- one wins the row lock, the
other's query simply skips that row and looks at the next one. SQLite
(local dev / the test suite) has no such clause; `settings.is_postgres`
gates it, exactly like `app.database.schema_isolation` already gates its
own Postgres-only behavior. SQLite's own single-writer model makes the
underlying claim query still correct there (the `WHERE status = 'QUEUED'`
clause itself excludes anything already claimed, and SQLite serializes
writers), just not proof of true concurrent-lock safety the way a real
multi-worker Postgres deployment needs -- that guarantee rests on
Postgres's row locking, unverifiable against SQLite alone (see this
feature's own report on what remains unverified without a real worker
deployment).
"""

from __future__ import annotations

import socket
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete as sa_delete, func, or_, select
from sqlalchemy.orm import Session

from app.core import document_storage
from app.core.config import settings
from app.core.enums import (
    BatchLifecycleStatus,
    ExtractionStatus,
    ImportAuditEventType,
    ImportJobStatus,
    ImportReviewStatus,
)
from app.models import (
    ImportAuditLogEntry,
    ImportBatch,
    ImportedBoqLineCandidate,
    ImportedClientAwardEvidenceCandidate,
    ImportedDocument,
    ImportedDocumentSegment,
    ImportedQuotationCandidate,
    ImportJob,
)
from app.services import import_service
from app.services.errors import ValidationError

__all__ = [
    "QueueSummary",
    "current_worker_id",
    "enqueue_import_job",
    "claim_next_import_job",
    "complete_import_job",
    "fail_import_job",
    "retry_import_job",
    "cancel_batch_jobs",
    "compute_queue_summary",
    "process_import_job",
    "compute_batch_lifecycle_status",
    "rename_import_batch",
    "archive_import_batch",
    "delete_import_batch",
]

#: How long a fixed retry backoff waits before a transiently-failed job
#: becomes claimable again -- short and constant (not exponential) is a
#: deliberate simplification: `max_attempts` (below) is what actually
#: bounds total retry cost, and this pipeline's failures are dominated by
#: "OCR engine unavailable"/"file moved" style causes that a short wait
#: doesn't meaningfully help or hurt, not rate-limited external APIs
#: where backoff shape matters.
_RETRY_BACKOFF_SECONDS = 30

#: How long a claimed job may run before being considered abandoned (its
#: worker crashed, was killed, or lost its database connection) and
#: reclaimed by another worker. Deliberately generous rather than
#: heartbeat-based: this pipeline processes one document at a time,
#: synchronously, with no natural mid-document checkpoint to heartbeat
#: from, and IMPORT_ARCHITECTURE.md's own measured worst case (~40s/page
#: OCR, §18) means even a genuinely large multi-page scan finishes in
#: single-digit minutes -- 30 minutes covers that with a wide safety
#: margin without needing a second moving part (a heartbeat thread/task)
#: whose own failure modes would need the same reasoning applied again.
_LEASE_DURATION_SECONDS = 30 * 60

#: A transient/infrastructure failure gets this many total attempts
#: (the initial claim plus two retries) before becoming terminally
#: FAILED -- never unbounded, per P3's explicit "do not endlessly retry
#: corrupt PDFs" (which, in practice, never even reach a retry: see
#: `ImportJobStatus`'s own docstring on why an ordinary bad document
#: succeeds as a JOB on its very first attempt).
_DEFAULT_MAX_ATTEMPTS = 3


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def current_worker_id() -> str:
    """A human-diagnosable identity for whichever process claims a job --
    purely informational (`ImportJob.worker_id`), never read by the
    claim/lease logic itself."""
    return f"{socket.gethostname()}-{os.getpid()}"


def enqueue_import_job(
    session: Session, document: ImportedDocument, *, max_attempts: int = _DEFAULT_MAX_ATTEMPTS
) -> ImportJob:
    """Creates a QUEUED job for `document`, immediately claimable. Safe
    to call more than once for the same document (returns the existing
    row unchanged rather than raising or creating a second one) -- the
    unique constraint on `imported_document_id` is the real guarantee;
    this check is just what turns a race into a clean no-op instead of
    an `IntegrityError` surfacing somewhere unexpected."""
    existing = session.execute(
        select(ImportJob).where(ImportJob.imported_document_id == document.id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    job = ImportJob(
        batch_id=document.batch_id,
        imported_document_id=document.id,
        status=ImportJobStatus.QUEUED,
        attempts=0,
        max_attempts=max_attempts,
        available_at=_now(),
    )
    session.add(job)
    session.flush()
    return job


def claim_next_import_job(session: Session, *, worker_id: str) -> ImportJob | None:
    """Atomically claims the single oldest eligible job -- either a
    QUEUED one whose `available_at` has arrived, or a PROCESSING one
    whose lease has expired (an abandoned job) -- and marks it
    PROCESSING under this worker's identity. Returns `None` when nothing
    is currently claimable; the caller (see `app/worker.py`) is expected
    to sleep briefly and try again.

    The caller MUST use a session dedicated to this call alone (commit
    immediately after, per this module's own docstring on why claim and
    process are separate transactions) -- this function itself only
    flushes, it never commits."""
    now = _now()
    eligible = or_(
        and_(ImportJob.status == ImportJobStatus.QUEUED, ImportJob.available_at <= now),
        and_(
            ImportJob.status == ImportJobStatus.PROCESSING,
            ImportJob.lease_expires_at.is_not(None),
            ImportJob.lease_expires_at < now,
        ),
    )
    stmt = select(ImportJob).where(eligible).order_by(ImportJob.id).limit(1)
    if settings.is_postgres:
        stmt = stmt.with_for_update(skip_locked=True)
    job = session.execute(stmt).scalars().first()
    if job is None:
        return None

    job.status = ImportJobStatus.PROCESSING
    job.attempts += 1
    job.worker_id = worker_id
    job.started_at = now
    job.lease_expires_at = now + timedelta(seconds=_LEASE_DURATION_SECONDS)
    job.last_error = None
    session.flush()
    return job


def complete_import_job(session: Session, job: ImportJob) -> ImportJob:
    """Marks a job SUCCEEDED -- called once `run_extraction` has run to
    completion for it, regardless of what `ExtractionStatus` the
    document itself ended up with (see `ImportJobStatus`'s own docstring:
    a cleanly-recorded FAILED/UNSUPPORTED document is still a
    successfully-run JOB)."""
    job.status = ImportJobStatus.SUCCEEDED
    job.completed_at = _now()
    job.last_error = None
    job.lease_expires_at = None
    session.flush()
    return job


def fail_import_job(session: Session, job: ImportJob, *, error: str) -> ImportJob:
    """Called only when processing a job raised an exception that
    escaped `run_extraction` itself -- a genuine infrastructure failure
    (a storage download error, a lost database connection, an unexpected
    bug), never an ordinary corrupt/unreadable document (that path
    always reaches `complete_import_job`; see `ImportJobStatus`'s own
    docstring). Retries with a short backoff while `attempts <
    max_attempts`; becomes terminally FAILED once exhausted. `error` is
    truncated defensively -- this is a diagnostic field, not a place a
    pathological exception message should be able to bloat a row."""
    job.last_error = error[:4000]
    if job.attempts < job.max_attempts:
        job.status = ImportJobStatus.QUEUED
        job.available_at = _now() + timedelta(seconds=_RETRY_BACKOFF_SECONDS)
        job.lease_expires_at = None
    else:
        job.status = ImportJobStatus.FAILED
        job.completed_at = _now()
        job.lease_expires_at = None
    session.flush()
    return job


def retry_import_job(session: Session, document: ImportedDocument) -> ImportJob:
    """The explicit "Retry" action a reviewer takes on a stalled/failed
    document (P8) -- re-queues the SAME job row for `document` (creating
    one first if none exists, e.g. for a document staged before this
    queue existed), never a duplicate document or a second job row, and
    resets its attempt counter so a document a reviewer has decided is
    worth retrying gets the full retry budget again rather than whatever
    attempts its first run already used up. Also resets the document's
    own `extraction_status` back to PENDING and clears any prior
    `extraction_error` -- the same "resumable" state `_ingest_batch`
    already recognizes -- so the queue summary and document table
    immediately reflect "queued again", not a stale FAILED badge sitting
    next to a job that's actually about to re-run."""
    job = session.execute(
        select(ImportJob).where(ImportJob.imported_document_id == document.id)
    ).scalar_one_or_none()
    if job is None:
        job = enqueue_import_job(session, document)

    now = _now()
    job.status = ImportJobStatus.QUEUED
    job.attempts = 0
    job.available_at = now
    job.started_at = None
    job.completed_at = None
    job.last_error = None
    job.lease_expires_at = None
    session.flush()

    old_status = document.extraction_status
    document.extraction_status = ExtractionStatus.PENDING
    document.extraction_error = None
    session.flush()

    session.add(
        ImportAuditLogEntry(
            imported_document_id=document.id,
            event_type=ImportAuditEventType.RETRIED,
            field_name="extraction_status",
            old_value=str(old_status),
            new_value=str(ExtractionStatus.PENDING),
            note="Re-queued via the review workspace's Retry action.",
        )
    )
    session.flush()
    return job


def cancel_batch_jobs(session: Session, batch: ImportBatch) -> int:
    """Stops future processing of every still-QUEUED job in `batch`
    (the "Cancel" action on a PROCESSING batch, P9) -- marks them
    terminally FAILED with a clear, honest reason, so the queue summary
    stops counting them as queued/processing. Deliberately does NOT
    touch a job that's already PROCESSING (a worker may genuinely be
    partway through it right now; forcibly killing an in-flight worker
    is out of scope for a database-row update) -- it will finish or its
    lease will expire and it will become reclaimable normally, unaffected
    by this call. Returns how many jobs were cancelled."""
    now = _now()
    stmt = select(ImportJob).where(ImportJob.batch_id == batch.id, ImportJob.status == ImportJobStatus.QUEUED)
    cancelled = 0
    for job in session.execute(stmt).scalars().all():
        job.status = ImportJobStatus.FAILED
        job.last_error = "Cancelled: the batch was cancelled before this document was processed."
        job.completed_at = now
        cancelled += 1
    session.flush()
    return cancelled


@dataclass(frozen=True)
class QueueSummary:
    """Job-table-derived counts (P16) -- distinct from, and a strict
    refinement of, `import_dashboard_service.ImportDashboardSummary`'s
    older combined "processing" bucket (PENDING+EXTRACTING+OCR_REQUIRED
    lumped together): `queued`/`processing` here come from the queue
    itself, which is what a reviewer watching a large batch actually
    wants to see move."""

    queued: int
    processing: int


def compute_queue_summary(session: Session, *, batch_id: int | None = None) -> QueueSummary:
    """Two plain `COUNT` queries against `import_jobs` -- correct and
    cheap at 10,000s-of-documents scale, exactly like
    `import_dashboard_service.compute_import_dashboard_summary`'s own
    counting style (never `len(session.query(...).all())`)."""
    base = select(func.count()).select_from(ImportJob)
    if batch_id is not None:
        base = base.where(ImportJob.batch_id == batch_id)

    def _count(status: ImportJobStatus) -> int:
        return session.execute(base.where(ImportJob.status == status)).scalar_one()

    return QueueSummary(
        queued=_count(ImportJobStatus.QUEUED),
        processing=_count(ImportJobStatus.PROCESSING),
    )


def process_import_job(session: Session, job: ImportJob) -> None:
    """Does the actual work for one already-CLAIMED job: restores the
    document's bytes to local disk if a redeploy/fresh worker means
    they're not there right now (`document_storage.ensure_present` --
    see that module's own docstring; a no-op when the file is already
    present or storage was never configured), then calls the existing,
    completely unmodified `import_service.run_extraction`. That function
    already never raises for an ordinary bad document (corrupt file, OCR
    engine unavailable, ...) -- it records `ExtractionStatus.FAILED`/
    `UNSUPPORTED`/`OCR_REQUIRED` itself and returns normally, which this
    always treats as job SUCCESS (see `ImportJobStatus`'s own docstring).
    Only a genuine exception escaping that (a database error, an
    unexpected bug, a storage/network failure) reaches `fail_import_job`
    here.

    Does not commit -- the caller (see `app/worker.py`) controls the
    transaction boundary, exactly like every other service function in
    this codebase."""
    document = session.get(ImportedDocument, job.imported_document_id)
    if document is None:
        # Defensive only -- nothing in this codebase ever deletes an
        # `ImportedDocument` out from under a live job (see P17's "a
        # job cannot be processed twice concurrently" / batch-delete
        # rules, which refuse to delete a batch with active jobs).
        fail_import_job(session, job, error=f"Imported document {job.imported_document_id} no longer exists.")
        return

    try:
        document_storage.ensure_present(
            original_path=document.original_path,
            storage_bucket=document.storage_bucket,
            storage_key=document.storage_key,
        )
        import_service.run_extraction(session, document)
    except Exception as exc:  # noqa: BLE001 - a worker-process bug must never crash the whole worker loop
        fail_import_job(session, job, error=str(exc))
        return

    complete_import_job(session, job)


# --- Batch lifecycle (P9/P10) --------------------------------------------------


def compute_batch_lifecycle_status(session: Session, batch: ImportBatch) -> BatchLifecycleStatus:
    """Derives `batch`'s current lifecycle state -- see
    `BatchLifecycleStatus`'s own docstring for exactly what each value
    means and what actions it permits. Four small `COUNT` queries, never
    loading document/job rows into Python -- correct and cheap at any
    per-batch document count this pipeline is designed for (P23's
    10,000-document target)."""
    if batch.archived_at is not None:
        return BatchLifecycleStatus.ARCHIVED

    total = session.execute(
        select(func.count()).select_from(ImportedDocument).where(ImportedDocument.batch_id == batch.id)
    ).scalar_one()
    if total == 0:
        return BatchLifecycleStatus.EMPTY

    active_jobs = session.execute(
        select(func.count())
        .select_from(ImportJob)
        .where(
            ImportJob.batch_id == batch.id,
            ImportJob.status.in_([ImportJobStatus.QUEUED, ImportJobStatus.PROCESSING]),
        )
    ).scalar_one()
    if active_jobs > 0:
        return BatchLifecycleStatus.PROCESSING

    needs_review = session.execute(
        select(func.count())
        .select_from(ImportedDocument)
        .where(ImportedDocument.batch_id == batch.id, ImportedDocument.review_status == ImportReviewStatus.NEEDS_REVIEW)
    ).scalar_one()
    if needs_review > 0:
        return BatchLifecycleStatus.STAGING

    return BatchLifecycleStatus.COMPLETED


def rename_import_batch(session: Session, batch: ImportBatch, *, label: str | None, notes: str | None) -> ImportBatch:
    """P10's deliberately minimal "Edit batch" -- label and optional
    notes only, no new batch, no change to any document it contains.
    Refuses on an archived batch (read-only, per `BatchLifecycleStatus`)."""
    if batch.archived_at is not None:
        raise ValidationError("This batch is archived and read-only. Nothing about it can be edited.")
    if label is not None:
        batch.label = label.strip() or None
    if notes is not None:
        batch.notes = notes.strip() or None
    session.flush()
    return batch


def archive_import_batch(session: Session, batch: ImportBatch) -> ImportBatch:
    """Marks a COMPLETED batch read-only (P9) -- never deletes or
    modifies a single `ImportedDocument`/business record; purely a flag
    on the batch itself. Refuses on anything still active (PROCESSING)
    or with documents still awaiting review (STAGING) -- archiving is
    for a batch that is genuinely done, not a way to hide one that
    isn't."""
    status = compute_batch_lifecycle_status(session, batch)
    if status == BatchLifecycleStatus.ARCHIVED:
        return batch
    if status not in (BatchLifecycleStatus.COMPLETED, BatchLifecycleStatus.EMPTY):
        raise ValidationError(
            f"Cannot archive a batch that is still {status.value.lower()} -- only a batch with no "
            "active jobs and nothing left awaiting review can be archived."
        )
    batch.archived_at = _now()
    session.flush()
    return batch


def _batch_has_confirmed_documents(session: Session, batch: ImportBatch) -> bool:
    return (
        session.execute(
            select(func.count())
            .select_from(ImportedDocument)
            .where(ImportedDocument.batch_id == batch.id, ImportedDocument.review_status == ImportReviewStatus.CONFIRMED)
        ).scalar_one()
        > 0
    )


def delete_import_batch(session: Session, batch: ImportBatch) -> None:
    """Hard-deletes `batch` and every `ImportedDocument` staged under it
    (and that document's own candidates/segments/jobs/audit log) --
    never a confirmed business record (`Quotation`/`Project`/`Client`/
    `ClientAwardEvidence`), which this refuses to touch entirely by
    refusing the delete outright the moment any document in the batch is
    CONFIRMED (P9/P17's "deleting an import batch cannot delete
    confirmed financial records" -- enforced here as a hard precondition,
    not a selective per-row skip that could partially succeed).

    Allowed only for EMPTY and STAGING-with-nothing-confirmed batches;
    raises `ValidationError` naming why otherwise (PROCESSING: cancel
    first; COMPLETED/ARCHIVED/STAGING-with-a-confirmation: archive
    instead -- see `BatchLifecycleStatus`). Deletes bottom-up (jobs/
    audit log/candidates/segments, then documents, then the batch
    itself) via bulk `DELETE` statements, never loading rows into Python
    -- correct and cheap even for a large staging-only batch."""
    status = compute_batch_lifecycle_status(session, batch)
    if status == BatchLifecycleStatus.PROCESSING:
        raise ValidationError("Cannot delete a batch while it has queued or processing jobs -- cancel it first.")
    if status in (BatchLifecycleStatus.COMPLETED, BatchLifecycleStatus.ARCHIVED):
        raise ValidationError("This batch has confirmed records and cannot be deleted -- archive it instead.")
    if status == BatchLifecycleStatus.STAGING and _batch_has_confirmed_documents(session, batch):
        raise ValidationError(
            "This batch contains at least one confirmed quotation and cannot be deleted -- archive it instead."
        )

    document_ids_stmt = select(ImportedDocument.id).where(ImportedDocument.batch_id == batch.id)
    document_ids = list(session.execute(document_ids_stmt).scalars().all())

    if document_ids:
        session.execute(sa_delete(ImportJob).where(ImportJob.imported_document_id.in_(document_ids)))
        session.execute(sa_delete(ImportAuditLogEntry).where(ImportAuditLogEntry.imported_document_id.in_(document_ids)))
        session.execute(
            sa_delete(ImportedBoqLineCandidate).where(ImportedBoqLineCandidate.imported_document_id.in_(document_ids))
        )
        session.execute(
            sa_delete(ImportedQuotationCandidate).where(ImportedQuotationCandidate.imported_document_id.in_(document_ids))
        )
        session.execute(
            sa_delete(ImportedClientAwardEvidenceCandidate).where(
                ImportedClientAwardEvidenceCandidate.imported_document_id.in_(document_ids)
            )
        )
        session.execute(sa_delete(ImportedDocumentSegment).where(ImportedDocumentSegment.imported_document_id.in_(document_ids)))
        session.execute(sa_delete(ImportedDocument).where(ImportedDocument.id.in_(document_ids)))

    session.delete(batch)
    session.flush()
