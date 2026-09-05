"""Tests for `app.cli.bulk_import` -- the folder-of-PDFs ingestion path
for a historical archive too large for the browser "Choose Files" flow
(tens of thousands of files). See that module's own docstring for why
this exists and what it reuses from the web-upload route rather than
duplicating.

Same in-memory-SQLite pattern as `test_api_imports.py`: `run_bulk_import`
opens its own sessions via `app.database.session.session_scope()`
(it is a standalone command, not a FastAPI route with an injectable
`Depends(get_db)`), so `db_session_module._engine`/`_SessionFactory` are
monkeypatched to the test database exactly like `api_test_support.
make_api_client` already does for the router tests -- this is real
`session_scope()` usage, not a mock of it.

Documents in these tests are staged (`stage_document_for_queue`) and
queued (`enqueue_import_job`) but never extracted -- P5 of the ingestion
pass is explicit that the bulk importer's own job ends at "queued";
extraction is the worker's job (`app/worker.py`), already covered by
`test_api_imports.py`'s `_process_queue` helper. A plain text payload
under a `.pdf` name is sufficient here: nothing under test reads the
file's actual content, only its bytes (for hashing/upload) and its path.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

import app.database.session as db_session_module
from app.cli import bulk_import
from app.core import document_storage
from app.core.enums import ExtractionStatus
from app.models.import_staging import ImportBatch, ImportedDocument, ImportJob
from app.services import import_service
from app.tests.api_test_support import make_memory_engine


def _mark_all_extraction_complete() -> None:
    """Simulates a worker having actually processed every currently
    staged document -- without this, `extraction_status` stays PENDING
    forever in these tests (no worker ever runs here), which
    `import_service.is_resumable_extraction_status` correctly treats as
    still-in-progress rather than a genuine duplicate (see that
    function's own docstring). A resumability test that wants to assert
    "already imported" (a true duplicate of a *finished* document, not
    an abandoned in-progress one) needs the prior run's documents to
    actually be in a terminal state first, exactly as they would be in
    reality once a worker got to them."""
    with db_session_module.session_scope() as session:
        for document in session.query(ImportedDocument).all():
            document.extraction_status = ExtractionStatus.EXTRACTION_COMPLETE


@pytest.fixture
def bulk_test_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine, None, None]:
    """Points `session_scope()` -- what every function in
    `app.cli.bulk_import` actually uses -- at a fresh in-memory database,
    exactly like `api_test_support.make_api_client` does for the FastAPI
    test client, but without needing a `TestClient`/HTTP layer at all
    since this module is a plain CLI, never a router."""
    engine = make_memory_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    original_engine = db_session_module._engine
    original_factory = db_session_module._SessionFactory
    db_session_module._engine = engine
    db_session_module._SessionFactory = factory
    try:
        yield engine
    finally:
        db_session_module._engine = original_engine
        db_session_module._SessionFactory = original_factory
        engine.dispose()


@pytest.fixture
def storage_configured(monkeypatch: pytest.MonkeyPatch) -> list[tuple[bytes, str]]:
    """Fakes durable storage as configured and captures every upload
    call's `(data, key)` -- real network calls are never made. A bulk
    run against `document_storage.is_configured() is False` is covered
    by its own dedicated test below instead."""
    monkeypatch.setattr(document_storage, "is_configured", lambda: True)
    uploads: list[tuple[bytes, str]] = []

    def _fake_upload(data: bytes, *, key: str, content_type: str = "", bucket: str = "", http_client=None):
        uploads.append((data, key))
        return (document_storage.DEFAULT_BUCKET, key)

    monkeypatch.setattr(document_storage, "upload_bytes", _fake_upload)
    return uploads


def _make_pdf(path: Path, content: bytes = b"%PDF-1.4 fake quotation content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class TestDiscoverPdfs:
    def test_finds_pdfs_recursively_and_ignores_other_files(self, tmp_path: Path):
        _make_pdf(tmp_path / "2016" / "Q001.pdf")
        _make_pdf(tmp_path / "2017" / "Q002.PDF")  # case-insensitive suffix
        _make_pdf(tmp_path / "2018" / "January" / "Q003.pdf")
        (tmp_path / "2018" / "readme.txt").parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "2018" / "readme.txt").write_text("not a pdf")
        (tmp_path / ".DS_Store").write_bytes(b"junk")

        found = sorted(str(p.relative_to(tmp_path)) for p in bulk_import.discover_pdfs(tmp_path))

        assert found == [
            "2016/Q001.pdf",
            "2017/Q002.PDF",
            "2018/January/Q003.pdf",
        ]

    def test_empty_directory_yields_nothing(self, tmp_path: Path):
        assert list(bulk_import.discover_pdfs(tmp_path)) == []


class TestRunBulkImportRequiresDurableStorage:
    def test_refuses_to_run_when_storage_is_not_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(document_storage, "is_configured", lambda: False)
        _make_pdf(tmp_path / "Q001.pdf")

        with pytest.raises(SystemExit, match="Durable storage is not configured"):
            bulk_import.run_bulk_import(tmp_path, batch_label="test", batch_id=None, commit_every=200)


class TestRunBulkImportNewFiles:
    def test_stages_uploads_and_queues_every_discovered_pdf(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        _make_pdf(tmp_path / "2018" / "Riyadh" / "QTN-104.pdf", b"content A")
        _make_pdf(tmp_path / "2019" / "QTN-200.pdf", b"content B")

        report = bulk_import.run_bulk_import(tmp_path, batch_label="2018-2019 archive", batch_id=None, commit_every=200)

        assert report.found == 2
        assert report.new == 2
        assert report.queued == 2
        assert report.already_imported == 0
        assert report.failed_storage == 0
        assert report.failed_read == 0
        assert len(storage_configured) == 2  # both files were actually uploaded

        with db_session_module.session_scope() as session:
            batches = session.query(ImportBatch).all()
            assert len(batches) == 1
            assert batches[0].label == "2018-2019 archive"

            documents = session.query(ImportedDocument).order_by(ImportedDocument.filename).all()
            assert [d.filename for d in documents] == ["QTN-104.pdf", "QTN-200.pdf"]
            assert all(d.batch_id == batches[0].id for d in documents)
            assert all(d.storage_bucket == document_storage.DEFAULT_BUCKET for d in documents)

            jobs = session.query(ImportJob).all()
            assert len(jobs) == 2
            assert {j.imported_document_id for j in jobs} == {d.id for d in documents}

    def test_preserves_relative_source_path_as_provenance(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        _make_pdf(tmp_path / "2018" / "Riyadh" / "QTN-104.pdf")

        bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=200)

        with db_session_module.session_scope() as session:
            document = session.query(ImportedDocument).one()
            assert document.filename == "QTN-104.pdf"  # never replaced by the relative path
            assert "2018/Riyadh/QTN-104.pdf" in (document.notes or "")

    def test_adds_to_an_existing_batch_when_batch_id_is_given(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        with db_session_module.session_scope() as session:
            existing_batch = import_service.create_import_batch(session, label="Already there")
            existing_batch_id = existing_batch.id

        _make_pdf(tmp_path / "Q001.pdf")
        report = bulk_import.run_bulk_import(tmp_path, batch_label=None, batch_id=existing_batch_id, commit_every=200)

        assert report.new == 1
        with db_session_module.session_scope() as session:
            assert session.query(ImportBatch).count() == 1  # no second batch was created
            document = session.query(ImportedDocument).one()
            assert document.batch_id == existing_batch_id

    def test_raises_when_given_batch_id_does_not_exist(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        _make_pdf(tmp_path / "Q001.pdf")
        with pytest.raises(SystemExit, match="not found"):
            bulk_import.run_bulk_import(tmp_path, batch_label=None, batch_id=999, commit_every=200)


class TestRunBulkImportIsResumable:
    def test_a_second_run_over_the_same_folder_finds_no_new_documents(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        _make_pdf(tmp_path / "2018" / "Q001.pdf", b"content A")
        _make_pdf(tmp_path / "2018" / "Q002.pdf", b"content B")

        first = bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=200)
        assert first.new == 2
        _mark_all_extraction_complete()  # a worker finished both before the second run

        second = bulk_import.run_bulk_import(tmp_path, batch_label="archive re-run", batch_id=None, commit_every=200)

        assert second.found == 2
        assert second.new == 0
        assert second.already_imported == 2
        assert second.queued == 0

        # No duplicate ImportJobs were created for either document, and no
        # second copy of either document's bytes was staged.
        with db_session_module.session_scope() as session:
            assert session.query(ImportedDocument).count() == 2
            assert session.query(ImportJob).count() == 2

    def test_a_new_file_added_between_runs_is_the_only_one_queued(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        _make_pdf(tmp_path / "Q001.pdf", b"content A")
        first = bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=200)
        assert first.new == 1
        _mark_all_extraction_complete()  # a worker finished Q001 before the second run

        _make_pdf(tmp_path / "Q002.pdf", b"content B")  # simulates the archive growing between runs
        second = bulk_import.run_bulk_import(tmp_path, batch_label="archive continued", batch_id=None, commit_every=200)

        assert second.found == 2
        assert second.new == 1
        assert second.already_imported == 1

    def test_interrupted_run_commits_completed_chunks_so_a_resume_does_not_redo_them(
        self, tmp_path: Path, bulk_test_db: Engine, storage_configured: list[tuple[bytes, str]]
    ):
        # commit_every=1 means every file is durably committed the moment
        # it's processed -- simulates the worst case of a crash between
        # every single file, and confirms nothing already committed is
        # redone by a second run.
        for i in range(5):
            _make_pdf(tmp_path / f"Q{i:03d}.pdf", f"content {i}".encode())

        first = bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=1)
        assert first.new == 5
        _mark_all_extraction_complete()  # a worker finished all 5 before the resume

        second = bulk_import.run_bulk_import(tmp_path, batch_label="archive resumed", batch_id=None, commit_every=1)
        assert second.new == 0
        assert second.already_imported == 5


class TestRunBulkImportStorageFailure:
    def test_a_storage_upload_failure_is_reported_and_the_document_is_not_enqueued(
        self, tmp_path: Path, bulk_test_db: Engine, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(document_storage, "is_configured", lambda: True)

        def _failing_upload(*args, **kwargs):
            raise document_storage.DocumentStorageError("Supabase Storage upload failed (503): down")

        monkeypatch.setattr(document_storage, "upload_bytes", _failing_upload)
        _make_pdf(tmp_path / "Q001.pdf")

        report = bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=200)

        assert report.found == 1
        assert report.new == 0
        assert report.queued == 0
        assert report.failed_storage == 1

        with db_session_module.session_scope() as session:
            # The document row exists (it was staged before the upload
            # was attempted) but P2's rule held: no job was ever created
            # for it, so it is not silently treated as safely archived.
            document = session.query(ImportedDocument).one()
            assert document.storage_bucket is None
            assert session.query(ImportJob).count() == 0

    def test_retrying_after_a_storage_failure_succeeds_without_duplicating_the_document(
        self, tmp_path: Path, bulk_test_db: Engine, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(document_storage, "is_configured", lambda: True)
        monkeypatch.setattr(
            document_storage,
            "upload_bytes",
            lambda *a, **k: (_ for _ in ()).throw(document_storage.DocumentStorageError("down")),
        )
        _make_pdf(tmp_path / "Q001.pdf")
        first = bulk_import.run_bulk_import(tmp_path, batch_label="archive", batch_id=None, commit_every=200)
        assert first.failed_storage == 1

        uploads: list[tuple[bytes, str]] = []
        monkeypatch.setattr(
            document_storage,
            "upload_bytes",
            lambda data, *, key, **k: uploads.append((data, key)) or (document_storage.DEFAULT_BUCKET, key),
        )
        second = bulk_import.run_bulk_import(tmp_path, batch_label="archive retry", batch_id=None, commit_every=200)

        assert second.found == 1
        assert second.new == 0
        assert second.resumed == 1  # the same document row, storage retried and now enqueued
        assert second.queued == 1
        assert len(uploads) == 1

        with db_session_module.session_scope() as session:
            assert session.query(ImportedDocument).count() == 1  # never duplicated
            assert session.query(ImportJob).count() == 1
