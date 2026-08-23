"""Project Detail: header + tabs (Overview, Quotations, Estimated Costs,
Actual Costs, Profitability, Documents)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from app.database.session import session_scope
from app.models import Project
from app.ui.costs.actual_costs_widget import ActualCostsWidget
from app.ui.costs.estimated_costs_widget import EstimatedCostsWidget
from app.ui.errors import run_guarded
from app.ui.projects.project_documents_tab import ProjectDocumentsTab
from app.ui.projects.project_overview_tab import ProjectOverviewTab
from app.ui.projects.project_profitability_tab import ProjectProfitabilityTab
from app.ui.projects.project_quotations_tab import ProjectQuotationsTab


class ProjectDetailPage(QWidget):
    def __init__(self, project_id: int, *, on_back: Callable[[], None]) -> None:
        super().__init__()
        self._project_id = project_id
        self._on_back = on_back

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        back_button = QPushButton("← Back to Projects")
        back_button.clicked.connect(self._on_back)
        header_row.addWidget(back_button)
        self._title_label = QLabel()
        self._title_label.setObjectName("pageTitle")
        header_row.addWidget(self._title_label)
        header_row.addStretch(1)
        edit_button = QPushButton("Edit Project")
        edit_button.clicked.connect(self._edit_project)
        header_row.addWidget(edit_button)
        layout.addLayout(header_row)

        self._tabs = QTabWidget()
        self._overview_tab = ProjectOverviewTab(project_id)
        self._quotations_tab = ProjectQuotationsTab(project_id)
        self._estimated_tab = EstimatedCostsWidget(project_id)
        self._actual_tab = ActualCostsWidget(project_id)
        self._profitability_tab = ProjectProfitabilityTab(project_id)
        self._documents_tab = ProjectDocumentsTab()

        self._tabs.addTab(self._overview_tab, "Overview")
        self._tabs.addTab(self._quotations_tab, "Quotations")
        self._tabs.addTab(self._estimated_tab, "Estimated Costs")
        self._tabs.addTab(self._actual_tab, "Actual Costs")
        self._tabs.addTab(self._profitability_tab, "Profitability")
        self._tabs.addTab(self._documents_tab, "Documents")
        self._tabs.currentChanged.connect(self._refresh_current_tab)
        layout.addWidget(self._tabs, 1)

    def refresh(self) -> None:
        def _load_name():
            with session_scope() as session:
                project = session.get(Project, self._project_id)
                return project.name if project else "Project"

        name = run_guarded(self, _load_name, context="loading project header")
        self._title_label.setText(name or "Project")
        self._refresh_current_tab()

    def _refresh_current_tab(self) -> None:
        widget = self._tabs.currentWidget()
        if widget is not None and hasattr(widget, "refresh"):
            widget.refresh()

    def _edit_project(self) -> None:
        from app.ui.projects.project_form_dialog import ProjectFormDialog

        if ProjectFormDialog(self, project_id=self._project_id).exec():
            self.refresh()
