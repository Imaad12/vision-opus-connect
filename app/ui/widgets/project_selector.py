"""A project dropdown with an inline "+" to create a new project, mirroring
`client_selector.py`. Used by the import review screen so matching an
existing project or creating a new one from extracted data never requires
leaving the review dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from app.database.session import session_scope
from app.services.project_service import list_projects


def _label_for(project) -> str:
    return f"{project.project_code + ' — ' if project.project_code else ''}{project.name}"


class ProjectSelector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        add_button = QPushButton("+ New Project")
        add_button.clicked.connect(self._add_project)

        layout.addWidget(self.combo, 1)
        layout.addWidget(add_button)

        self.reload()

    def reload(self, *, select_project_id: int | None = None) -> None:
        current = select_project_id if select_project_id is not None else self.selected_project_id()
        self.combo.clear()
        with session_scope() as session:
            for project in list_projects(session):
                self.combo.addItem(_label_for(project), project.id)
        if current is not None:
            index = self.combo.findData(current)
            if index >= 0:
                self.combo.setCurrentIndex(index)

    def selected_project_id(self) -> int | None:
        return self.combo.currentData()

    def set_selected_project_id(self, project_id: int | None) -> None:
        if project_id is None:
            return
        index = self.combo.findData(project_id)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def _add_project(self) -> None:
        from app.ui.projects.project_form_dialog import ProjectFormDialog

        dialog = ProjectFormDialog(self)
        if dialog.exec() and dialog.created_project_id is not None:
            self.reload(select_project_id=dialog.created_project_id)
