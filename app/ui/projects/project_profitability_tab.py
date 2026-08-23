"""Profitability tab: the dedicated deep-dive view. Reuses the exact same
`ProfitabilityView` as the Overview tab's financial summary so the two
screens can never show conflicting numbers for the same project."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from app.database.session import session_scope
from app.models import Project
from app.services.financial_service import build_project_financial_snapshot
from app.ui.errors import run_guarded
from app.ui.widgets.profitability_view import ProfitabilityView


class ProjectProfitabilityTab(QWidget):
    def __init__(self, project_id: int) -> None:
        super().__init__()
        self._project_id = project_id

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(12)

        note = QLabel(
            "All figures are computed by the financial engine from recorded data — "
            "nothing here is calculated independently by the UI."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._view = ProfitabilityView()
        layout.addWidget(self._view)
        layout.addStretch(1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                return build_project_financial_snapshot(session, project)

        snapshot = run_guarded(self, _load, context="loading profitability")
        if snapshot is not None:
            self._view.set_snapshot(snapshot)
