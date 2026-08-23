"""Project Overview: identity/dates at a glance, plus the full financial
summary (via the shared ProfitabilityView, so it's never a second,
diverging copy of the numbers shown on the Profitability tab)."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from sqlalchemy.orm import joinedload

from app.database.session import session_scope
from app.models import Project
from app.services.financial_service import build_project_financial_snapshot
from app.ui.errors import run_guarded
from app.ui.formatting import format_date
from app.ui.widgets.profitability_view import ProfitabilityView


class ProjectOverviewTab(QWidget):
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
        layout.setSpacing(16)

        info_frame = QFrame()
        info_frame.setObjectName("card")
        info_grid = QGridLayout(info_frame)
        info_grid.setContentsMargins(16, 14, 16, 14)
        info_grid.setHorizontalSpacing(24)
        info_grid.setVerticalSpacing(6)

        self._name_label = QLabel()
        self._name_label.setObjectName("sectionTitle")
        self._client_label = QLabel()
        self._status_label = QLabel()
        self._code_label = QLabel()
        self._currency_label = QLabel()
        self._start_label = QLabel()
        self._planned_completion_label = QLabel()
        self._actual_completion_label = QLabel()
        self._description_label = QLabel()
        self._description_label.setWordWrap(True)

        info_grid.addWidget(self._name_label, 0, 0, 1, 4)
        self._add_field(info_grid, 1, 0, "Client", self._client_label)
        self._add_field(info_grid, 1, 2, "Status", self._status_label)
        self._add_field(info_grid, 2, 0, "Project Number", self._code_label)
        self._add_field(info_grid, 2, 2, "Currency", self._currency_label)
        self._add_field(info_grid, 3, 0, "Start Date", self._start_label)
        self._add_field(info_grid, 3, 2, "Expected Completion", self._planned_completion_label)
        self._add_field(info_grid, 4, 0, "Actual Completion", self._actual_completion_label)
        info_grid.addWidget(self._description_label, 5, 0, 1, 4)

        layout.addWidget(info_frame)

        summary_heading = QLabel("Financial Summary")
        summary_heading.setObjectName("sectionTitle")
        layout.addWidget(summary_heading)

        self._profitability_view = ProfitabilityView()
        layout.addWidget(self._profitability_view)
        layout.addStretch(1)

    @staticmethod
    def _add_field(grid: QGridLayout, row: int, col: int, label: str, value_widget: QLabel) -> None:
        label_widget = QLabel(label)
        label_widget.setObjectName("mutedLabel")
        grid.addWidget(label_widget, row, col)
        grid.addWidget(value_widget, row, col + 1)

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                project = session.get(
                    Project, self._project_id, options=[joinedload(Project.client)]
                )
                snapshot = build_project_financial_snapshot(session, project)
                return project, snapshot

        result = run_guarded(self, _load, context="loading project overview")
        if result is None:
            return
        project, snapshot = result

        self._name_label.setText(project.name)
        self._client_label.setText(project.client.name if project.client else "—")
        self._status_label.setText(project.status.value.replace("_", " ").title())
        self._code_label.setText(project.project_code or "—")
        self._currency_label.setText(project.contract_currency.value)
        self._start_label.setText(format_date(project.start_date))
        self._planned_completion_label.setText(format_date(project.planned_completion_date))
        self._actual_completion_label.setText(format_date(project.actual_completion_date))
        self._description_label.setText(project.description or "")

        self._profitability_view.set_snapshot(snapshot)
