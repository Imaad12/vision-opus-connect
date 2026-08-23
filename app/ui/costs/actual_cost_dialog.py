"""Add-an-actual-cost dialog."""

from __future__ import annotations

from datetime import date as date_type

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
)

from app.core.enums import CostPaymentStatus
from app.core.financial_engine import calculate_net_of_tax
from app.database.session import session_scope
from app.models import Project
from app.services.cost_service import add_actual_cost
from app.services.lookup_service import list_cost_categories, list_vendors
from app.ui.errors import run_guarded
from app.ui.formatting import format_money
from app.ui.widgets.money_field import MoneyLineEdit


class ActualCostDialog(QDialog):
    def __init__(self, parent, *, project: Project) -> None:
        super().__init__(parent)
        self._project = project
        self.setWindowTitle("Add Actual Cost")
        self.setMinimumWidth(440)

        self._date = QDateEdit(calendarPopup=True)
        self._date.setDate(QDate.currentDate())

        self._category = QComboBox()
        with session_scope() as session:
            for category in list_cost_categories(session):
                self._category.addItem(category.name, category.id)
            self._vendors = list_vendors(session)

        self._vendor = QComboBox()
        self._vendor.addItem("— None —", None)
        for vendor in self._vendors:
            self._vendor.addItem(vendor.name, vendor.id)

        self._description = QLineEdit()
        self._reference_number = QLineEdit()
        self._reference_number.setPlaceholderText("supplier invoice / receipt number")

        self._gross_amount = MoneyLineEdit(placeholder="required")
        self._tax_amount = MoneyLineEdit(placeholder="optional")
        self._net_amount_label = QLineEdit()
        self._net_amount_label.setReadOnly(True)
        self._net_amount_label.setPlaceholderText("computed")
        self._gross_amount.textChanged.connect(self._update_net_amount)
        self._tax_amount.textChanged.connect(self._update_net_amount)

        self._non_recoverable = QCheckBox("Tax is non-recoverable (counts as project cost)")

        self._payment_status = QComboBox()
        for status in CostPaymentStatus:
            self._payment_status.addItem(status.value.replace("_", " ").title(), status)

        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(50)

        form = QFormLayout(self)
        form.addRow("Date", self._date)
        form.addRow("Category *", self._category)
        form.addRow("Supplier / Subcontractor", self._vendor)
        form.addRow("Description", self._description)
        form.addRow("Reference / Invoice Number", self._reference_number)
        form.addRow("Gross Amount *", self._gross_amount)
        form.addRow("Tax Amount", self._tax_amount)
        form.addRow("Net Amount (computed)", self._net_amount_label)
        form.addRow("", self._non_recoverable)
        form.addRow("Payment Status", self._payment_status)
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_net_amount(self) -> None:
        net = calculate_net_of_tax(self._gross_amount.decimal_value(), self._tax_amount.decimal_value())
        self._net_amount_label.setText(format_money(net, self._project.contract_currency) if net is not None else "")

    def _on_save(self) -> None:
        def _save():
            qdate: QDate = self._date.date()
            incurred_date: date_type = qdate.toPython()
            with session_scope() as session:
                add_actual_cost(
                    session,
                    self._project,
                    cost_category_id=self._category.currentData(),
                    amount=self._gross_amount.decimal_value(),
                    tax_amount=self._tax_amount.decimal_value(),
                    is_tax_recoverable=not self._non_recoverable.isChecked(),
                    incurred_date=incurred_date,
                    description=self._description.text(),
                    vendor_id=self._vendor.currentData(),
                    reference_number=self._reference_number.text(),
                    payment_status=self._payment_status.currentData(),
                    currency=self._project.contract_currency,
                    notes=self._notes.toPlainText(),
                )
            return True

        if run_guarded(self, _save, context="adding actual cost"):
            self.accept()
