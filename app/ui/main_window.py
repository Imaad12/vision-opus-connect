"""Application shell: persistent sidebar navigation + a stacked content area.

Primary navigation (Dashboard, Projects, Quotations, Costs, Analytics,
Settings) matches the Phase 3 brief. Client management is reached from
Settings rather than the primary sidebar — see UI_ARCHITECTURE.md.

This module wires pages together; it contains no database access and no
financial calculations of its own.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.analytics_page import AnalyticsPage
from app.ui.clients.clients_page import ClientsPage
from app.ui.costs.costs_page import CostsPage
from app.ui.dashboard.dashboard_page import DashboardPage
from app.ui.imports.imports_page import ImportsPage
from app.ui.projects.project_detail_page import ProjectDetailPage
from app.ui.projects.projects_list_page import ProjectsListPage
from app.ui.quotations.quotations_page import QuotationsPage
from app.ui.settings_page import SettingsPage

NAV_ITEMS = [
    ("dashboard", "Dashboard"),
    ("projects", "Projects"),
    ("quotations", "Quotations"),
    ("costs", "Costs"),
    ("imports", "Imports"),
    ("analytics", "Analytics"),
    ("settings", "Settings"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vision Contracting — Profit & Estimating")
        self.setMinimumSize(1180, 760)
        self.resize(1360, 860)

        central = QWidget()
        central.setObjectName("centralArea")
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._detail_page: ProjectDetailPage | None = None
        self._pages: dict[str, QWidget] = {}
        self._register_pages()

        self._show_page("dashboard")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("VISION CONTRACTING")
        title.setObjectName("appTitle")
        subtitle = QLabel("PROFIT & ESTIMATING")
        subtitle.setObjectName("appSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for key, label in NAV_ITEMS:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, k=key: self._show_page(k))
            layout.addWidget(button)
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button

        layout.addStretch(1)
        return sidebar

    def _register_pages(self) -> None:
        self._pages["dashboard"] = DashboardPage()
        self._pages["projects"] = ProjectsListPage(open_project=self.open_project_detail)
        self._pages["quotations"] = QuotationsPage()
        self._pages["costs"] = CostsPage()
        self._pages["imports"] = ImportsPage()
        self._pages["analytics"] = AnalyticsPage()

        settings_page = SettingsPage()
        settings_page.on_manage_clients(self.open_clients)
        self._pages["settings"] = settings_page

        self._clients_page = ClientsPage()

        for page in self._pages.values():
            self._stack.addWidget(page)
        self._stack.addWidget(self._clients_page)

    def _show_page(self, key: str) -> None:
        page = self._pages[key]
        self._stack.setCurrentWidget(page)
        self._nav_buttons[key].setChecked(True)
        if hasattr(page, "refresh"):
            page.refresh()

    def open_project_detail(self, project_id: int) -> None:
        if self._detail_page is not None:
            self._stack.removeWidget(self._detail_page)
            self._detail_page.deleteLater()

        self._detail_page = ProjectDetailPage(project_id, on_back=self._back_to_projects)
        self._stack.addWidget(self._detail_page)
        self._stack.setCurrentWidget(self._detail_page)
        self._nav_group.setExclusive(False)
        for button in self._nav_buttons.values():
            button.setChecked(False)
        self._nav_group.setExclusive(True)
        self._detail_page.refresh()

    def _back_to_projects(self) -> None:
        self._show_page("projects")

    def open_clients(self) -> None:
        self._nav_group.setExclusive(False)
        for button in self._nav_buttons.values():
            button.setChecked(False)
        self._nav_group.setExclusive(True)
        self._stack.setCurrentWidget(self._clients_page)
        self._clients_page.refresh()
