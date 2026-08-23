"""A single, professional QSS theme for the whole application.

Deliberately restrained: one accent color, a neutral palette, and no
animation — this is business software for a construction company, not a
consumer app. Colors are also exposed as constants so widgets that need to
paint outside QSS (e.g. custom-drawn badges) stay consistent with it.
"""

from __future__ import annotations

INK = "#1A1D1F"
INK_MUTED = "#5F6368"
BORDER = "#D8DCE0"
SURFACE = "#FFFFFF"
SURFACE_MUTED = "#F4F5F6"
ACCENT = "#1F4E5F"
ACCENT_MUTED = "#E7EEF0"
SIDEBAR_BG = "#16232A"
SIDEBAR_TEXT = "#C9D6DA"
SIDEBAR_TEXT_ACTIVE = "#FFFFFF"
SIDEBAR_ACTIVE_BG = "#1F4E5F"

FAVORABLE = "#1E7B45"
UNFAVORABLE = "#B3261E"

FONT_FAMILY = '"Segoe UI", "Helvetica Neue", Arial, sans-serif'

STYLESHEET = f"""
* {{
    font-family: {FONT_FAMILY};
    color: {INK};
}}

QMainWindow, QWidget#centralArea {{
    background: {SURFACE_MUTED};
}}

QWidget#sidebar {{
    background: {SIDEBAR_BG};
}}

QPushButton#navButton {{
    text-align: left;
    padding: 10px 18px;
    border: none;
    border-radius: 0;
    color: {SIDEBAR_TEXT};
    background: transparent;
    font-size: 13px;
}}

QPushButton#navButton:hover {{
    background: #1D2E36;
    color: {SIDEBAR_TEXT_ACTIVE};
}}

QPushButton#navButton:checked {{
    background: {SIDEBAR_ACTIVE_BG};
    color: {SIDEBAR_TEXT_ACTIVE};
    font-weight: 600;
}}

QLabel#appTitle {{
    color: {SIDEBAR_TEXT_ACTIVE};
    font-size: 15px;
    font-weight: 700;
    padding: 18px 18px 6px 18px;
}}

QLabel#appSubtitle {{
    color: {SIDEBAR_TEXT};
    font-size: 11px;
    padding: 0 18px 16px 18px;
}}

QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 700;
    color: {INK};
}}

QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {INK};
}}

QLabel#mutedLabel {{
    color: {INK_MUTED};
    font-size: 12px;
}}

QFrame#card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QLabel#kpiValue {{
    font-size: 20px;
    font-weight: 700;
    color: {INK};
}}

QLabel#kpiLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {INK_MUTED};
    letter-spacing: 0.4px;
}}

QTableView, QTableWidget {{
    background: {SURFACE};
    alternate-background-color: {SURFACE_MUTED};
    gridline-color: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: {ACCENT_MUTED};
    selection-color: {INK};
}}

QHeaderView::section {{
    background: {SURFACE_MUTED};
    color: {INK_MUTED};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
    font-size: 11px;
}}

QLineEdit, QComboBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    min-height: 22px;
}}

QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 14px;
    font-size: 12px;
}}

QPushButton:hover {{
    background: {ACCENT_MUTED};
}}

QPushButton#primaryButton {{
    background: {ACCENT};
    color: {SURFACE};
    border: 1px solid {ACCENT};
    font-weight: 600;
}}

QPushButton#primaryButton:hover {{
    background: #173C49;
}}

QPushButton#dangerButton {{
    color: {UNFAVORABLE};
    border: 1px solid {UNFAVORABLE};
    background: {SURFACE};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    padding: 8px 16px;
    color: {INK_MUTED};
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}
"""
