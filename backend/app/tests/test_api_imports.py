"""End-to-end tests for the `/imports` API routes
(`app/api/routers/imports.py`) -- the REST surface over the existing
`app/services/import_service.py` pipeline.

Same `make_api_client`/`make_memory_engine` pattern as
`test_api_quotations.py`. Uploads go through a real temp directory
(`settings.imports_storage_dir`, monkeypatched per-test to a pytest
`tmp_path`) so every test exercises the real file-write -> real
`ingest_quotation_batch` path end-to-end, never a mock of the pipeline
itself.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

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


def test_upload_stages_a_document_and_writes_it_to_persistent_storage(
    api_client: TestClient, storage_dir: Path
):
    batch = api_client.post("/imports/batches", json={"label": "Pilot"}).json()
    response = _upload(api_client, batch["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["outcomes"]) == 1
    outcome = body["outcomes"][0]
    assert outcome["action"] == "staged"
    assert outcome["filename"] == "quote.txt"
    assert outcome["document_id"] is not None
    assert outcome["error"] is None

    # The uploaded bytes actually landed in the configured persistent
    # storage directory (not a discarded temp file) -- see this feature's
    # own report on why that matters for "uploaded documents remain
    # traceable".
    saved_files = list(storage_dir.glob("*.txt"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == QUOTATION_TEXT


def test_upload_updates_batch_counts(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"])
    refreshed = api_client.get(f"/imports/batches/{batch['id']}").json()
    assert refreshed["staged_count"] == 1
    assert refreshed["completed_at"] is not None


def test_upload_duplicate_file_is_skipped_not_restaged(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    _upload(api_client, batch["id"], filename="first.txt")
    response = _upload(api_client, batch["id"], filename="second.txt")  # same content
    outcome = response.json()["outcomes"][0]
    assert outcome["action"] == "skipped_duplicate"

    documents = api_client.get(f"/imports/batches/{batch['id']}/documents").json()
    assert len(documents) == 1  # the duplicate never got its own row


def test_upload_no_files_is_422(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    response = api_client.post(f"/imports/batches/{batch['id']}/documents", files=[])
    assert response.status_code == 422


def test_upload_to_missing_batch_is_404(api_client: TestClient):
    response = _upload(api_client, 999)
    assert response.status_code == 404


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
    upload = _upload(api_client, batch["id"]).json()
    document_id = upload["outcomes"][0]["document_id"]

    document = api_client.get(f"/imports/documents/{document_id}").json()
    assert document["review_status"] == "NEEDS_REVIEW"
    candidate = document["quotation_candidate"]
    assert candidate is not None
    assert candidate["quotation_number"] == "Q-2024-0091"
    assert candidate["client_name"] == "ABC Holdings"
    assert candidate["project_name"] == "Villa ABC Renovation"


def test_get_missing_document_is_404(api_client: TestClient):
    response = api_client.get("/imports/documents/999")
    assert response.status_code == 404


def test_confirm_document_creates_client_project_and_quotation(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    upload = _upload(api_client, batch["id"]).json()
    document_id = upload["outcomes"][0]["document_id"]

    response = api_client.post(
        f"/imports/documents/{document_id}/confirm",
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
    upload = _upload(api_client, batch["id"]).json()
    document_id = upload["outcomes"][0]["document_id"]

    response = api_client.post(f"/imports/documents/{document_id}/confirm", json={})
    assert response.status_code == 422


def test_confirm_missing_document_is_404(api_client: TestClient):
    response = api_client.post("/imports/documents/999/confirm", json={"new_client_name": "X"})
    assert response.status_code == 404


def test_reject_document(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    upload = _upload(api_client, batch["id"]).json()
    document_id = upload["outcomes"][0]["document_id"]

    response = api_client.post(
        f"/imports/documents/{document_id}/reject", json={"reason": "Illegible scan"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_status"] == "REJECTED"


def test_reject_missing_document_is_404(api_client: TestClient):
    response = api_client.post("/imports/documents/999/reject", json={})
    assert response.status_code == 404


def test_confirmed_document_cannot_be_rejected_afterward(api_client: TestClient):
    batch = api_client.post("/imports/batches", json={}).json()
    upload = _upload(api_client, batch["id"]).json()
    document_id = upload["outcomes"][0]["document_id"]
    api_client.post(
        f"/imports/documents/{document_id}/confirm", json={"new_client_name": "X", "new_project_name": "Y"}
    )
    response = api_client.post(f"/imports/documents/{document_id}/reject", json={})
    assert response.status_code == 422


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
