"""Costs: pick a project, then manage its estimated and actual costs.

Costs are inherently project-scoped (every EstimatedCost/ActualCost row
belongs to exactly one project), so this page is a thin project selector
wrapped around the same reusable widgets used in the Project Detail tabs —
no logic is duplicated between the two entry points.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from app.database.session import session_scope
from app.services.project_service import list_projects
from app.ui.costs.actual_costs_widget import ActualCostsWidget
from app.ui.costs.estimated_costs_widget import EstimatedCostsWidget
from app.ui.errors import run_guarded


class CostsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._current_project_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Costs")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        picker_row = QHBoxLayout()
        picker_row.addWidget(QLabel("Project:"))
        self._project_selector = QComboBox()
        self._project_selector.setMinimumWidth(280)
        self._project_selector.currentIndexChanged.connect(self._on_project_changed)
        picker_row.addWidget(self._project_selector)
        picker_row.addStretch(1)
        layout.addLayout(picker_row)

        self._tabs = QTabWidget()
        self._estimated_widget: EstimatedCostsWidget | None = None
        self._actual_widget: ActualCostsWidget | None = None
        layout.addWidget(self._tabs, 1)

        self._empty_label = QLabel("Create a project first to manage its costs.")
        self._empty_label.setObjectName("mutedLabel")
        layout.addWidget(self._empty_label)
        self._empty_label.hide()

    def refresh(self) -> None:
        def _load():
            with session_scope() as session:
                return list_projects(session)

        projects = run_guarded(self, _load, context="loading projects for cost management")
        if projects is None:
            return

        previous = self._project_selector.currentData()
        self._project_selector.blockSignals(True)
        self._project_selector.clear()
        for project in projects:
            label = f"{project.project_code + ' — ' if project.project_code else ''}{project.name}"
            self._project_selector.addItem(label, project.id)
        self._project_selector.blockSignals(False)

        if not projects:
            self._tabs.hide()
            self._empty_label.show()
            return
        self._tabs.show()
        self._empty_label.hide()

        index = self._project_selector.findData(previous) if previous else 0
        self._project_selector.setCurrentIndex(max(index, 0))
        self._on_project_changed()

    def _on_project_changed(self) -> None:
        project_id = self._project_selector.currentData()
        if project_id is None or project_id == self._current_project_id:
            if project_id is not None:
                self._refresh_tabs()
            return
        self._current_project_id = project_id

        self._tabs.clear()
        self._estimated_widget = EstimatedCostsWidget(project_id)
        self._actual_widget = ActualCostsWidget(project_id)
        self._tabs.addTab(self._estimated_widget, "Estimated Costs")
        self._tabs.addTab(self._actual_widget, "Actual Costs")
        self._refresh_tabs()

    def _refresh_tabs(self) -> None:
        if self._estimated_widget:
            self._estimated_widget.refresh()
        if self._actual_widget:
            self._actual_widget.refresh()
