"""End-to-end tests for the `/imports` API routes
(`app/api/routers/imports.py`) -- the REST surface over the existing
`app/services/import_service.py` pipeline.

Same `make_api_client`/`make_memory_engine` pattern as
`test_api_quotations.py`. Uploads go through a real temp directory
(`settings.imports_storage_dir`, monkeypatched per-test to a pytest
`tmp_path`) so every test exercises the real file-write -> real
`ingest_quotation_batch` path end-to-end, never a mock of the pipeline
itself.

Upload processing runs as a FastAPI `BackgroundTasks` job (see the
router's own docstring on why), not inline in the request -- but
Starlette's `TestClient` runs a request's background tasks to
completion before `client.post(...)` returns control to the caller
(verified empirically here, not just assumed), so these tests can still
assert on the resulting document/state immediately after the upload
call returns, exactly as if it were synchronous. `api_test_support.
make_api_client` also redirects `app.database.session`'s module-level
engine/factory (what the background task's `session_scope()` actually
resolves to) at the same in-memory test database `get_db` uses -- see
that fixture's own comment on the real production-database hang this
closes.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import settings
from app.tests.api_test_support import make_api_client, make_memory_engine

QUOTATION_TEXT = """\
Quotation Number: Q-2024-0091
Quotation Date: 15/03/2024
Client Name: ABC Holdings
Project Name: Villa ABC Renovation
Project Number: VC-2024-018
Net Amount: 1,250,000.00
VAT Amount: 62,500.00
Total Including VAT: 1,312,500.00
"""


@pytest.fixture
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "imports-storage"
    monkeypatch.setattr(settings, "imports_storage_dir", directory)
    return directory


@pytest.fixture
def api_client(storage_dir: Path) -> Generator[TestClient, None, None]:
    engine = make_memory_engine()
    granted = {"quotations.create"}
    yield from make_api_client(engine, granted)
    engine.dispose()


def _upload(client: TestClient, batch_id: int, *, filename: str = "quote.txt", text: str = QUOTATION_TEXT):
    return client.post(
        f"/imports/batches/{batch_id}/documents",
        files=[("files", (filename, text.encode("utf-8"), "text/plain"))],
    )


def _upload_and_get_document(
    client: TestClient, batch_id: int, *, filename: str = "quote.txt", text: str = QUOTATION_TEXT
) -> dict:
    """Uploads one file and returns the resulting `ImportedDocumentSummary`
    row from the batch's document list -- the background-processed
    equivalent of the old synchronous "outcomes[0]" shortcut."""
    _upload(client, batch_id, filename=filename, text=text)
    documents = client.get(f"/imports/batches/{batch_id}/documents").json()
    return next(d for d in documents if d["filename"] == filename)


def _make_pdf_with_text(path: Path, text: str, *, extra_blank_pages: int = 0) -> None:
    """Same real-PyMuPDF-fixture convention `test_document_preview.py`
    already uses -- a genuine PDF a reviewer's browser could open, not a
    mock, so these tests exercise the actual PDF importer + page-preview
    rendering path end-to-end."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    for _ in range(extra_blank_pages):
        doc.new_page()
    doc.save(path)
    doc.close()


def _upload_pdf_and_get_document(
    client: TestClient, batch_id: int, pdf_path: Path, *, filename: str = "quote.pdf"
) -> dict:
    client.post(
        f"/imports/batches/{batch_id}/documents",
        files=[("files", (filename, pdf_path.read_bytes(), "application/pdf"))],
    )
    documents = client.get(f"/imports/batches/{batch_id}/documents").json()
    return next(d for d in documents if d["filename"] == filename)


def test_create_batch(api_client: TestClient):
    response = api_client.post("/imports/batches", json={"label": "2018 archive box 3"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["label"] == "2018 archive box 3"
    assert body["staged_count"] == 0
    assert body["completed_at"] is None


def test_create_batch_without_label(api_client: TestClient):
    response = api_client.post("/imports/batches", json={})
    assert response.status_code == 201, response.text
    assert response.json()["label"] is None


def test_list_batches(api_client: TestClient):
    api_client.post("/imports/batches", json={"label": "First"})
    api_client.post("/imports/batches", json={"label": "Second"})
    response = api_client.get("/imports/batches")
    assert response.status_code == 200
    labels = {b["label"] for b in response.json()}
    assert labels == {"First", "Second"}


def test_get_missing_batch_is_404(api_client: TestClient):
    response = api_client.get("/imports/batches/999")
    assert response.status_code == 404


def test_upload_response_accepts_files_without_synchronous_outcomes(api_client: TestClient):
    """The upload endpoint itself only confirms bytes were received and
    background processing was scheduled (202 Accepted) -- it can't know
    staged/duplicate/failed yet, since that determination now happens
    after this response is sent (see the router's own docstring)."""
    batch = api_client.post("/imports/batches", json={"label": "Pilot"}).json()
    response = _upload(api_client, batch["id"])
    assert response.status_code == 202, response.text
    assert response.json() == {"accepted_files": ["quote.txt"]}


def test_upload_eventually_stages_a_document_and_writes_it_to_persistent_storage(
    api_client: TestClient, storage_dir: Path
):
    batch = api_client.post("/imports/batches", json={"label": "Pilot"}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    assert document["extraction_status"] in ("EXTRACTING", "EXTRACTION_COMPLETE", "PENDING")
    assert document["review_status"] == "NEEDS_REVIEW"

    # The uploaded bytes actually landed in the configured persistent
    # storage directory (not a discarded temp file) -- see this feature's
    # own report on why that matters for "uploaded documents remain
    # traceable".
    saved_files = list(storage_dir.glob("*.txt"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == QUOTATION_TEXT


def test_upload_reaches_a_terminal_extraction_status_for_a_real_text_quotation(api_client: TestClient):
    """A deterministic (non-OCR) text document's extraction is fast and
    fully synchronous inside the background task -- by the time the
    document is visible at all, it should already be past PENDING/
    EXTRACTING and have real candidate data, proving the pipeline
    actually ran end-to-end rather than just creating a staged row."""
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])
    assert document["extraction_status"] == "EXTRACTION_COMPLETE"
    assert document["extraction_error"] is None


def test_upload_updates_batch_counts(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"])
    refreshed = api_client.get(f"/imports/batches/{batch['id']}").json()
    assert refreshed["staged_count"] == 1
    assert refreshed["completed_at"] is not None


def test_upload_duplicate_file_is_skipped_not_restaged(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"], filename="first.txt")
    _upload(api_client, batch["id"], filename="second.txt")  # same content

    documents = api_client.get(f"/imports/batches/{batch['id']}/documents").json()
    assert len(documents) == 1  # the duplicate never got its own row

    refreshed = api_client.get(f"/imports/batches/{batch['id']}").json()
    assert refreshed["skipped_duplicate_count"] == 1

    summary = api_client.get(f"/imports/batches/{batch['id']}/summary").json()
    assert summary["duplicates"] == 1


def test_upload_no_files_is_422(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    response = api_client.post(f"/imports/batches/{batch['id']}/documents", files=[])
    assert response.status_code == 422


def test_upload_to_missing_batch_is_404(api_client: TestClient):
    response = _upload(api_client, 999)
    assert response.status_code == 404
    # A 404 on the batch must be checked before anything is written or
    # scheduled -- no orphaned file, no background task for a batch that
    # was never confirmed to exist.


def test_list_batch_documents(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"])
    documents = api_client.get(f"/imports/batches/{batch['id']}/documents").json()
    assert len(documents) == 1
    assert documents[0]["filename"] == "quote.txt"
    assert documents[0]["batch_id"] == batch["id"]


def test_batch_summary_counts(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"])
    summary = api_client.get(f"/imports/batches/{batch['id']}/summary").json()
    assert summary["total"] == 1
    assert summary["needs_review"] == 1
    assert summary["confirmed"] == 0
    assert summary["duplicates"] == 0


def test_get_document_returns_extracted_candidate_fields(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    detail = api_client.get(f"/imports/documents/{document['id']}").json()
    assert detail["review_status"] == "NEEDS_REVIEW"
    candidate = detail["quotation_candidate"]
    assert candidate is not None
    assert candidate["quotation_number"] == "Q-2024-0091"
    assert candidate["client_name"] == "ABC Holdings"
    assert candidate["project_name"] == "Villa ABC Renovation"


def test_get_missing_document_is_404(api_client: TestClient):
    response = api_client.get("/imports/documents/999")
    assert response.status_code == 404


def test_confirm_document_creates_client_project_and_quotation(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.post(
        f"/imports/documents/{document['id']}/confirm",
        json={
            "new_client_name": "ABC Holdings",
            "new_project_name": "Villa ABC Renovation",
            "include_boq": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "CONFIRMED"
    assert body["resulting_client_id"] is not None
    assert body["resulting_project_id"] is not None
    assert body["resulting_quotation_id"] is not None

    # A real, listable quotation now exists -- proves confirm_import
    # actually reached the real business tables via the existing
    # quotation_service, not just flipped a status flag. (quotations.view
    # is a separate permission from quotations.create -- granted here
    # only to make this one assertion possible.)
    api_client.granted.add("quotations.view")
    quotations = api_client.get("/quotations").json()
    assert any(q["id"] == body["resulting_quotation_id"] for q in quotations)


def test_confirm_document_with_no_client_info_is_422(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])
    response = api_client.post(f"/imports/documents/{document['id']}/confirm", json={})
    assert response.status_code == 422


def test_confirm_missing_document_is_404(api_client: TestClient):
    response = api_client.post("/imports/documents/999/confirm", json={"new_client_name": "X"})
    assert response.status_code == 404


def test_reject_document(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.post(
        f"/imports/documents/{document['id']}/reject", json={"reason": "Illegible scan"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_status"] == "REJECTED"


def test_reject_missing_document_is_404(api_client: TestClient):
    response = api_client.post("/imports/documents/999/reject", json={})
    assert response.status_code == 404


def test_confirmed_document_cannot_be_rejected_afterward(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])
    api_client.post(
        f"/imports/documents/{document['id']}/confirm",
        json={"new_client_name": "X", "new_project_name": "Y"},
    )
    response = api_client.post(f"/imports/documents/{document['id']}/reject", json={})
    assert response.status_code == 422


# ---- Review workspace (P2): field corrections + page preview ----


def test_update_candidate_field_applies_correction(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.patch(
        f"/imports/documents/{document['id']}/candidate",
        json={"client_name": "ABC Holdings LLC (corrected)"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["quotation_candidate"]["client_name"] == "ABC Holdings LLC (corrected)"

    # The correction is actually persisted, not just echoed back.
    detail = api_client.get(f"/imports/documents/{document['id']}").json()
    assert detail["quotation_candidate"]["client_name"] == "ABC Holdings LLC (corrected)"


def test_update_candidate_marks_edited_field_high_confidence(api_client: TestClient):
    """A field the reviewer actually changes must have its confidence
    marker cleared to HIGH -- otherwise a LOW/NEEDS_REVIEW flag from
    extraction time would keep blocking `confirm_import`'s OCR gate
    (`compute_ocr_confidence_status`) even after a human corrected it,
    silently defeating the entire point of letting them edit it."""
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.patch(
        f"/imports/documents/{document['id']}/candidate",
        json={"net_value": "1300000.00"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["quotation_candidate"]["field_confidence"]["net_value"] == "HIGH"


def test_update_candidate_omitted_fields_are_untouched(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.patch(
        f"/imports/documents/{document['id']}/candidate",
        json={"client_name": "New Name"},
    )
    assert response.status_code == 200, response.text
    # project_name wasn't in the request body at all -- exclude_unset
    # means it must survive unchanged, not be nulled out.
    assert response.json()["quotation_candidate"]["project_name"] == "Villa ABC Renovation"


def test_update_candidate_after_confirm_is_422(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])
    api_client.post(
        f"/imports/documents/{document['id']}/confirm",
        json={"new_client_name": "X", "new_project_name": "Y"},
    )

    response = api_client.patch(
        f"/imports/documents/{document['id']}/candidate",
        json={"client_name": "Too late"},
    )
    assert response.status_code == 422


def test_update_candidate_missing_document_is_404(api_client: TestClient):
    response = api_client.patch("/imports/documents/999/candidate", json={"client_name": "X"})
    assert response.status_code == 404


def test_get_document_page_count_is_none_for_non_pdf(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])
    detail = api_client.get(f"/imports/documents/{document['id']}").json()
    assert detail["page_count"] is None


def test_get_document_reports_page_count_for_pdf(api_client: TestClient, tmp_path: Path):
    pdf_path = tmp_path / "source.pdf"
    _make_pdf_with_text(pdf_path, "Quotation Number: QTN/2024/017", extra_blank_pages=2)

    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_pdf_and_get_document(api_client, batch["id"], pdf_path)

    detail = api_client.get(f"/imports/documents/{document['id']}").json()
    assert detail["page_count"] == 3


def test_document_page_preview_returns_a_real_png(api_client: TestClient, tmp_path: Path):
    pdf_path = tmp_path / "source.pdf"
    _make_pdf_with_text(pdf_path, "Quotation Number: QTN/2024/017")

    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_pdf_and_get_document(api_client, batch["id"], pdf_path)

    response = api_client.get(f"/imports/documents/{document['id']}/pages/1")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_document_page_preview_out_of_range_is_422(api_client: TestClient, tmp_path: Path):
    pdf_path = tmp_path / "source.pdf"
    _make_pdf_with_text(pdf_path, "Quotation Number: QTN/2024/017")

    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_pdf_and_get_document(api_client, batch["id"], pdf_path)

    response = api_client.get(f"/imports/documents/{document['id']}/pages/99")
    assert response.status_code == 422


def test_document_page_preview_non_pdf_is_422(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    document = _upload_and_get_document(api_client, batch["id"])

    response = api_client.get(f"/imports/documents/{document['id']}/pages/1")
    assert response.status_code == 422


def test_document_page_preview_missing_document_is_404(api_client: TestClient):
    response = api_client.get("/imports/documents/999/pages/1")
    assert response.status_code == 404


# ---- Permission gating ----


def test_all_routes_require_quotations_create(api_client: TestClient):
    api_client.granted.discard("quotations.create")

    assert api_client.post("/imports/batches", json={}).status_code == 403
    assert api_client.get("/imports/batches").status_code == 403
    assert api_client.get("/imports/batches/1").status_code == 403
    assert api_client.get("/imports/batches/1/summary").status_code == 403
    assert api_client.get("/imports/batches/1/documents").status_code == 403
    assert _upload(api_client, 1).status_code == 403
    assert api_client.get("/imports/documents/1").status_code == 403
    assert api_client.post("/imports/documents/1/confirm", json={}).status_code == 403
    assert api_client.post("/imports/documents/1/reject", json={}).status_code == 403
    assert api_client.patch("/imports/documents/1/candidate", json={}).status_code == 403
    assert api_client.get("/imports/documents/1/pages/1").status_code == 403


def test_missing_bearer_token_is_401(storage_dir: Path):
    from sqlalchemy.orm import sessionmaker

    from app.api.deps import get_db, get_supabase_auth
    from app.api.main import create_app
    from app.tests.api_test_support import FakeSupabaseAuth

    engine = make_memory_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: iter([factory()])
    app.dependency_overrides[get_supabase_auth] = lambda: FakeSupabaseAuth(set())

    with TestClient(app) as client:
        response = client.get("/imports/batches")

    assert response.status_code == 401
    engine.dispose()
