"""Standalone ingestion worker process (P4 of the production-reliability
pass -- see this feature's own report).

This is the ONLY thing that ever calls `import_service.run_extraction`
for a document uploaded through the web API (`POST /imports/batches/
{id}/documents`) -- the API process itself never runs extraction, not
inline and not as a `BackgroundTasks` job (see `app/api/routers/
imports.py`'s own module docstring on why that mechanism was removed).
Run this as its own Render service (`render.yaml`'s `vinco-import-worker`,
same Docker image as the API, different `dockerCommand`):

    python -m app.worker

A plain, single-process, one-document-at-a-time polling loop --
deliberately conservative (P4's "keep worker concurrency conservative
initially... reliability before maximum throughput"), not a thread/
process pool. Throughput scales by running more worker service
instances (Render lets a service scale horizontally); each instance is
still one-at-a-time internally, and `import_queue_service.
claim_next_import_job`'s `SELECT ... FOR UPDATE SKIP LOCKED` (on
PostgreSQL) is what makes running several instances at once safe -- two
workers claiming from the same table at the same moment can never claim
the same job.

Shutdown: SIGTERM/SIGINT (what Render sends on a deploy/restart) sets a
flag checked between jobs -- the loop finishes whatever job it's
currently processing (never abandons a claimed job mid-write) and then
exits cleanly, rather than stopping instantly mid-database-write. A
harder kill (SIGKILL, an OOM) is still safe at the queue level even
without this: the claimed job's lease (`ImportJob.lease_expires_at`)
simply expires and `claim_next_import_job` treats it as abandoned and
reclaimable -- see that function's own docstring.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from app.core.logging_config import configure_logging
from app.database.session import session_scope
from app.models import ImportJob
from app.services import import_queue_service

logger = logging.getLogger("app.worker")

#: How long to sleep between polls when nothing is claimable -- short
#: enough that a freshly-queued document starts processing within a few
#: seconds of upload, long enough that an idle worker doesn't hammer the
#: database with empty claim queries all day.
_IDLE_POLL_SECONDS = 3.0


class _ShutdownRequested(RuntimeError):
    """Raised from the signal handler to unwind out of a blocking sleep
    immediately, rather than waiting for it to finish -- see
    `_sleep_unless_shutting_down`."""


class _ShutdownFlag:
    def __init__(self) -> None:
        self.requested = False

    def request(self, *_args: object) -> None:
        self.requested = True


def _sleep_unless_shutting_down(seconds: float, flag: _ShutdownFlag) -> None:
    """Sleeps in short slices so a signal arriving mid-sleep is noticed
    within a fraction of a second, not up to `_IDLE_POLL_SECONDS` late --
    matters for Render's own deploy grace period, which is not unlimited."""
    deadline = time.monotonic() + seconds
    while not flag.requested and time.monotonic() < deadline:
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))


def run_worker_loop(*, max_iterations: int | None = None) -> None:
    """The loop itself, factored out from `main()` so a test can run a
    bounded number of iterations instead of forever (`max_iterations`) --
    production always calls this with the default (run until shutdown)."""
    flag = _ShutdownFlag()
    signal.signal(signal.SIGTERM, flag.request)
    signal.signal(signal.SIGINT, flag.request)

    worker_id = import_queue_service.current_worker_id()
    logger.info("Import worker %s starting", worker_id)

    iterations = 0
    while not flag.requested:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1

        with session_scope() as session:
            job = import_queue_service.claim_next_import_job(session, worker_id=worker_id)
            job_id = job.id if job is not None else None
            document_id = job.imported_document_id if job is not None else None

        if job_id is None:
            _sleep_unless_shutting_down(_IDLE_POLL_SECONDS, flag)
            continue

        logger.info("Claimed import job %s (document %s)", job_id, document_id)
        try:
            with session_scope() as session:
                job = session.get(ImportJob, job_id)
                if job is not None:
                    import_queue_service.process_import_job(session, job)
        except Exception:  # noqa: BLE001 - one bad job must never kill the whole worker process
            logger.exception("Unhandled error processing import job %s -- continuing to the next job", job_id)

    logger.info("Import worker %s shutting down cleanly", worker_id)


def main() -> None:
    configure_logging()
    run_worker_loop()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - a crash here must still exit non-zero for Render to notice and restart
        logger.exception("Import worker crashed")
        sys.exit(1)
