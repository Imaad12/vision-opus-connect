"""Add-a-line dialog for the current estimate revision."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit

from app.core.financial_engine import calculate_line_total
from app.database.session import session_scope
from app.models import EstimateRevision, Project
from app.services.cost_service import add_estimated_cost_line
from app.services.lookup_service import list_cost_categories
from app.ui.errors import run_guarded
from app.ui.widgets.money_field import MoneyLineEdit


class EstimatedCostDialog(QDialog):
    def __init__(self, parent, *, project: Project, revision: EstimateRevision) -> None:
        super().__init__(parent)
        self._project = project
        self._revision = revision
        self.setWindowTitle(f"Add Estimate Line — Revision {revision.revision_number}")
        self.setMinimumWidth(420)

        self._category = QComboBox()
        with session_scope() as session:
            for category in list_cost_categories(session):
                self._category.addItem(category.name, category.id)

        self._description = QLineEdit()
        self._quantity = QLineEdit()
        self._quantity.setPlaceholderText("optional")
        self._unit = QLineEdit()
        self._unit.setPlaceholderText("e.g. m2, no, LS")
        self._unit_rate = MoneyLineEdit(placeholder="optional")
        self._amount = MoneyLineEdit(placeholder="required unless quantity + unit rate given")
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(50)

        for field in (self._quantity, self._unit_rate, self._amount):
            field.textChanged.connect(self._recompute_amount)

        form = QFormLayout(self)
        form.addRow("Category *", self._category)
        form.addRow("Description", self._description)
        form.addRow("Quantity", self._quantity)
        form.addRow("Unit", self._unit)
        form.addRow("Unit Rate", self._unit_rate)
        form.addRow("Amount *", self._amount)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _recompute_amount(self) -> None:
        try:
            quantity = Decimal(self._quantity.text()) if self._quantity.text().strip() else None
        except Exception:
            quantity = None
        unit_rate = self._unit_rate.decimal_value()
        computed = calculate_line_total(quantity, unit_rate)
        if computed is not None:
            self._amount.blockSignals(True)
            self._amount.set_decimal_value(computed)
            self._amount.blockSignals(False)

    def _on_save(self) -> None:
        def _save():
            quantity = Decimal(self._quantity.text()) if self._quantity.text().strip() else None
            with session_scope() as session:
                add_estimated_cost_line(
                    session,
                    self._project,
                    self._revision,
                    cost_category_id=self._category.currentData(),
                    description=self._description.text(),
                    quantity=quantity,
                    unit=self._unit.text(),
                    unit_rate=self._unit_rate.decimal_value(),
                    amount=self._amount.decimal_value(),
                    currency=self._project.contract_currency,
                    notes=self._notes.toPlainText(),
                )
            return True

        if run_guarded(self, _save, context="adding estimate line"):
            self.accept()
