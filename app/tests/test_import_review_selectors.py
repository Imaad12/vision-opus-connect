"""Regression test for a pre-merge production-readiness finding:
`ClientSelector`/`ProjectSelector` (used by the Phase 4 import review
dialog to pick or create the client/project a confirmed import attaches
to) populated their combo box with no "nothing selected" placeholder.
Qt's `QComboBox` auto-selects the first added item whenever a combo goes
from empty to non-empty, so as soon as *any* client/project already
existed in the database, these widgets silently returned a real (and
generally arbitrary — alphabetically first) client/project ID even when
no match was suggested and the reviewer never touched the widget.

That made `import_service.confirm_import`'s "select an existing client/
project or create a new one" validation unreachable from the UI: a
reviewer who didn't notice the pre-filled dropdown could confirm an
imported quotation against a completely unrelated existing project.

The fix adds a `data=None` placeholder as the first combo entry so "no
explicit selection" genuinely reports `None`. This test constructs both
widgets against a database that already has an (unrelated) client and
project, and asserts neither widget silently reports that unrelated
record as selected.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.database.session as db_session_module  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.services.client_service import create_client  # noqa: E402
from app.services.project_service import create_project  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wired_global_session(monkeypatch):
    """`ClientSelector`/`ProjectSelector` call `app.database.session.session_scope()`
    directly (they are standalone, reusable widgets with no session
    parameter) rather than the `db_session` fixture used elsewhere in this
    suite. This points that global session factory at an isolated
    in-memory database for the duration of the test only; `monkeypatch`
    restores the previous (unset) module state afterward, so no other test
    file is affected."""
    engine = db_session_module.get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setattr(db_session_module, "_engine", engine)
    monkeypatch.setattr(db_session_module, "_SessionFactory", factory)
    yield engine
    engine.dispose()


def test_client_selector_defaults_to_no_selection_even_with_existing_clients(qapp, wired_global_session) -> None:
    with db_session_module.session_scope() as session:
        create_client(session, name="Alpha Holdings")  # sorts first alphabetically

    from app.ui.widgets.client_selector import ClientSelector

    selector = ClientSelector()
    assert selector.selected_client_id() is None


def test_project_selector_defaults_to_no_selection_even_with_existing_projects(qapp, wired_global_session) -> None:
    with db_session_module.session_scope() as session:
        client = create_client(session, name="Alpha Holdings")
        create_project(session, name="Alpha Project", client_id=client.id)

    from app.ui.widgets.project_selector import ProjectSelector

    selector = ProjectSelector()
    assert selector.selected_project_id() is None


def test_client_selector_explicit_selection_still_works(qapp, wired_global_session) -> None:
    with db_session_module.session_scope() as session:
        client = create_client(session, name="Alpha Holdings")
        client_id = client.id

    from app.ui.widgets.client_selector import ClientSelector

    selector = ClientSelector()
    selector.set_selected_client_id(client_id)
    assert selector.selected_client_id() == client_id


def test_project_selector_explicit_selection_still_works(qapp, wired_global_session) -> None:
    with db_session_module.session_scope() as session:
        client = create_client(session, name="Alpha Holdings")
        project = create_project(session, name="Alpha Project", client_id=client.id)
        project_id = project.id

    from app.ui.widgets.project_selector import ProjectSelector

    selector = ProjectSelector()
    selector.set_selected_project_id(project_id)
    assert selector.selected_project_id() == project_id


def test_client_selector_reload_preserves_no_selection_by_default(qapp, wired_global_session) -> None:
    from app.ui.widgets.client_selector import ClientSelector

    selector = ClientSelector()
    assert selector.selected_client_id() is None

    with db_session_module.session_scope() as session:
        create_client(session, name="Beta Holdings")

    selector.reload()
    assert selector.selected_client_id() is None
