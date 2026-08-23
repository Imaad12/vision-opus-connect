"""A minimal "pick a project" dialog, for flows that start from a global
page (e.g. creating a quotation from the Quotations page) rather than from
inside a specific project's detail page."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout

from app.database.session import session_scope
from app.services.project_service import list_projects


class ProjectPickerDialog(QDialog):
    def __init__(self, parent=None, *, title: str = "Select Project") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        self._combo = QComboBox()
        with session_scope() as session:
            for project in list_projects(session):
                label = f"{project.project_code + ' — ' if project.project_code else ''}{project.name}"
                self._combo.addItem(label, project.id)

        form = QFormLayout(self)
        form.addRow("Project", self._combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def selected_project_id(self) -> int | None:
        return self._combo.currentData()
