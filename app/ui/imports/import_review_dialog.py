"""Review one staged import: source document info, editable quotation
candidate fields, editable BOQ candidate rows, and client/project
matching — ending in either Confirm (which opens the required summary
step, `ImportConfirmationDialog`) or Reject.

Nothing here computes a financial figure or writes to the database
directly; every persisted change goes through `app.services.import_service`
(see UI_ARCHITECTURE.md for the import pipeline / UI-service boundary).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.enums import ConfidenceLevel, Currency, ExtractionStatus, ImportReviewStatus
from app.core.import_normalization import parse_date_maybe
from app.database.session import session_scope
from app.services.import_matching import suggest_client_matches, suggest_project_matches, suggest_quotation_matches
from app.services.import_service import get_imported_document, reject_import, update_boq_line_candidate, update_quotation_candidate
from app.ui.confidence_labels import AMOUNT_FLAGGED_LABEL, AMOUNT_OK_LABEL, CONFIDENCE_COLORS, CONFIDENCE_LABELS
from app.ui.errors import run_guarded
from app.ui.formatting import format_date, format_money, format_quantity
from app.ui.imports.import_confirmation_dialog import ImportConfirmationDialog
from app.ui.widgets.client_selector import ClientSelector
from app.ui.widgets.project_selector import ProjectSelector
from app.ui.widgets.status_badge import Badge

_MONEY_FIELDS = ("net_value", "tax_value", "gross_value")
_TEXT_FIELDS = ("quotation_number", "client_name", "project_name", "project_number", "payment_terms")
_DATE_FIELDS = ("quotation_date", "valid_until")

_BOQ_COLUMNS = ["Item", "Description", "Category/Trade", "Unit", "Quantity", "Unit Rate", "Extracted Amount", "Calculated Amount", "Status"]


def _parse_date_input(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return parse_date_maybe(text)


def _parse_decimal_input(text: str) -> Decimal | None:
    text = text.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:  # noqa: BLE001
        return None


class ImportReviewDialog(QDialog):
    def __init__(self, document_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document_id = document_id
        self.setWindowTitle("Review Import")
        self.setMinimumSize(860, 700)

        self._layout = QVBoxLayout(self)
        self._field_widgets: dict[str, QWidget] = {}
        self._boq_row_ids: list[int] = []
        self._loading_boq = False
        self._currency_combo: QComboBox | None = None

        self._load_and_build()

    # --- Loading -------------------------------------------------------------

    def _load_and_build(self) -> None:
        with session_scope() as session:
            document = get_imported_document(session, self._document_id)
            if document is None:
                self._layout.addWidget(QLabel("This staged import no longer exists."))
                return

            self._extraction_status = document.extraction_status
            self._review_status = document.review_status
            source_info = {
                "filename": document.filename,
                "extension": document.extension.upper(),
                "original_path": document.original_path,
                "imported_at": document.created_at,
                "extraction_status": document.extraction_status,
                "extraction_error": document.extraction_error,
            }
            candidate = document.quotation_candidate
            candidate_data = None
            if candidate is not None:
                candidate_data = {
                    "id": candidate.id,
                    "quotation_number": candidate.quotation_number,
                    "quotation_date": candidate.quotation_date,
                    "client_name": candidate.client_name,
                    "project_name": candidate.project_name,
                    "project_number": candidate.project_number,
                    "description": candidate.description,
                    "currency": candidate.currency,
                    "net_value": candidate.net_value,
                    "tax_value": candidate.tax_value,
                    "gross_value": candidate.gross_value,
                    "valid_until": candidate.valid_until,
                    "payment_terms": candidate.payment_terms,
                    "notes": candidate.notes,
                    "field_confidence": json.loads(candidate.field_confidence) if candidate.field_confidence else {},
                }
                project_matches = [
                    (p.id, f"{p.project_code + ' — ' if p.project_code else ''}{p.name}", p.client.name)
                    for p in suggest_project_matches(session, candidate)
                ]
                client_matches = [(c.id, c.name) for c in suggest_client_matches(session, candidate)]
                quotation_matches = [
                    (m.reference_number, m.current_version_date, m.current_version_total)
                    for m in suggest_quotation_matches(session, candidate)
                ]
            else:
                project_matches, client_matches, quotation_matches = [], [], []

            boq_rows = [
                {
                    "id": line.id,
                    "item_number": line.item_number,
                    "description": line.description,
                    "category_label": line.category_label,
                    "unit": line.unit,
                    "quantity": line.quantity,
                    "unit_rate": line.unit_rate,
                    "extracted_amount": line.extracted_amount,
                    "calculated_amount": line.calculated_amount,
                    "amount_flagged": line.amount_flagged,
                }
                for line in document.boq_line_candidates
            ]

        self._build_source_section(source_info)

        if self._extraction_status in (
            ExtractionStatus.FAILED,
            ExtractionStatus.UNSUPPORTED,
            ExtractionStatus.OCR_REQUIRED,
        ):
            self._build_terminal_section(source_info)
            return

        if candidate_data is not None:
            self._build_quotation_section(candidate_data)
        self._build_boq_section(boq_rows)
        self._build_matching_section(candidate_data, project_matches, client_matches, quotation_matches)
        self._build_action_buttons()

        if self._review_status != ImportReviewStatus.NEEDS_REVIEW:
            self._disable_editing()

    # --- Section builders ------------------------------------------------------

    def _build_source_section(self, info: dict) -> None:
        group = QGroupBox("Source Document")
        form = QFormLayout(group)
        form.addRow("Filename", QLabel(info["filename"]))
        form.addRow("File Type", QLabel(info["extension"]))
        form.addRow("Original Path", QLabel(info["original_path"]))
        form.addRow("Import Date", QLabel(format_date(info["imported_at"])))
        form.addRow("Extraction Status", QLabel(info["extraction_status"].value.replace("_", " ").title()))
        self._layout.addWidget(group)

    def _build_terminal_section(self, info: dict) -> None:
        message = info["extraction_error"] or "This document could not be reviewed."
        label = QLabel(message)
        label.setWordWrap(True)
        self._layout.addWidget(label)

        buttons = QHBoxLayout()
        if self._review_status == ImportReviewStatus.NEEDS_REVIEW:
            reject_button = QPushButton("Reject")
            reject_button.clicked.connect(self._reject)
            buttons.addWidget(reject_button)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons.addWidget(close_button)
        self._layout.addLayout(buttons)

    def _confidence_badge(self, field_confidence: dict, field_name: str) -> QWidget | None:
        value = field_confidence.get(field_name)
        if not value:
            return None
        try:
            level = ConfidenceLevel(value)
        except ValueError:
            return None
        return Badge(CONFIDENCE_LABELS[level], CONFIDENCE_COLORS[level])

    def _build_quotation_section(self, candidate: dict) -> None:
        group = QGroupBox("Quotation Information")
        form = QFormLayout(group)
        confidence = candidate["field_confidence"]

        for field_name, label in (
            ("quotation_number", "Quotation Number"),
            ("client_name", "Client"),
            ("project_name", "Project Name"),
            ("project_number", "Project Number"),
            ("payment_terms", "Payment Terms"),
        ):
            edit = QLineEdit(candidate[field_name] or "")
            edit.editingFinished.connect(lambda f=field_name, w=edit: self._save_text_field(f, w))
            self._field_widgets[field_name] = edit
            form.addRow(label, self._with_badge(edit, confidence, field_name))

        for field_name, label in (("quotation_date", "Quotation Date"), ("valid_until", "Valid Until")):
            value = candidate[field_name]
            edit = QLineEdit(value.isoformat() if value else "")
            edit.setPlaceholderText("YYYY-MM-DD")
            edit.editingFinished.connect(lambda f=field_name, w=edit: self._save_date_field(f, w))
            self._field_widgets[field_name] = edit
            form.addRow(label, self._with_badge(edit, confidence, field_name))

        currency_combo = QComboBox()
        for currency in Currency:
            currency_combo.addItem(currency.value, currency.value)
        if candidate["currency"] and currency_combo.findData(candidate["currency"]) < 0:
            currency_combo.addItem(candidate["currency"], candidate["currency"])
        if candidate["currency"]:
            currency_combo.setCurrentIndex(currency_combo.findData(candidate["currency"]))
        currency_combo.currentIndexChanged.connect(
            lambda _i: self._save_field("currency", currency_combo.currentData())
        )
        self._field_widgets["currency"] = currency_combo
        self._currency_combo = currency_combo
        form.addRow("Currency", currency_combo)

        for field_name, label in (
            ("net_value", "Net Quoted Value"),
            ("tax_value", "Tax / VAT"),
            ("gross_value", "Gross Quoted Value"),
        ):
            edit = QLineEdit("" if candidate[field_name] is None else str(candidate[field_name]))
            edit.setPlaceholderText("0.00")
            edit.editingFinished.connect(lambda f=field_name, w=edit: self._save_money_field(f, w))
            self._field_widgets[field_name] = edit
            form.addRow(label, self._with_badge(edit, confidence, field_name))

        description = QPlainTextEdit(candidate["description"] or "")
        description.setFixedHeight(50)
        description.textChanged.connect(lambda w=description: self._save_field("description", w.toPlainText()))
        self._field_widgets["description"] = description
        form.addRow("Description", description)

        notes = QPlainTextEdit(candidate["notes"] or "")
        notes.setFixedHeight(50)
        notes.textChanged.connect(lambda w=notes: self._save_field("notes", w.toPlainText()))
        self._field_widgets["notes"] = notes
        form.addRow("Notes", notes)

        self._layout.addWidget(group)

    def _with_badge(self, widget: QWidget, confidence: dict, field_name: str) -> QWidget:
        badge = self._confidence_badge(confidence, field_name)
        if badge is None:
            return widget
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(widget, 1)
        row.addWidget(badge)
        return wrapper

    def _build_boq_section(self, rows: list[dict]) -> None:
        if not rows:
            return
        group = QGroupBox("Bill of Quantities (BOQ)")
        layout = QVBoxLayout(group)
        note = QLabel(
            "Extracted amounts are shown as found in the source document. Calculated amounts "
            "(quantity x unit rate) are computed by the application and are never overwritten "
            "by the extracted value, or vice versa."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        table = QTableWidget(len(rows), len(_BOQ_COLUMNS))
        table.setHorizontalHeaderLabels(_BOQ_COLUMNS)
        self._boq_table = table
        self._boq_row_ids = [row["id"] for row in rows]

        self._loading_boq = True
        for row_index, row in enumerate(rows):
            table.setItem(row_index, 0, QTableWidgetItem(row["item_number"] or ""))
            table.setItem(row_index, 1, QTableWidgetItem(row["description"] or ""))
            table.setItem(row_index, 2, QTableWidgetItem(row["category_label"] or ""))
            table.setItem(row_index, 3, QTableWidgetItem(row["unit"] or ""))
            table.setItem(row_index, 4, QTableWidgetItem(format_quantity(row["quantity"])))
            table.setItem(row_index, 5, QTableWidgetItem("" if row["unit_rate"] is None else str(row["unit_rate"])))
            table.setItem(
                row_index, 6, QTableWidgetItem("" if row["extracted_amount"] is None else str(row["extracted_amount"]))
            )
            calculated_item = QTableWidgetItem(format_money(row["calculated_amount"], self._current_currency()))
            calculated_item.setFlags(calculated_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_index, 7, calculated_item)
            status_label = AMOUNT_FLAGGED_LABEL if row["amount_flagged"] else AMOUNT_OK_LABEL
            status_item = QTableWidgetItem(status_label)
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_index, 8, status_item)
        self._loading_boq = False

        table.itemChanged.connect(self._on_boq_item_changed)
        layout.addWidget(table)
        self._layout.addWidget(group)

    def _build_matching_section(
        self, candidate: dict | None, project_matches: list, client_matches: list, quotation_matches: list
    ) -> None:
        group = QGroupBox("Client & Project")
        layout = QVBoxLayout(group)

        layout.addWidget(QLabel("Client"))
        self._client_selector = ClientSelector()
        if client_matches:
            hint = QLabel(f"Potential existing client: {client_matches[0][1]}")
            hint.setObjectName("pageSubtitle")
            layout.addWidget(hint)
            self._client_selector.set_selected_client_id(client_matches[0][0])
        elif candidate and candidate["client_name"]:
            hint = QLabel(f"No existing client matched \"{candidate['client_name']}\" — select or create one below.")
            hint.setObjectName("pageSubtitle")
            layout.addWidget(hint)
        layout.addWidget(self._client_selector)

        layout.addWidget(QLabel("Project"))
        self._project_selector = ProjectSelector()
        if project_matches:
            project_id, label, client_name = project_matches[0]
            hint = QLabel(f"Potential existing project: {label} (Client: {client_name})")
            hint.setObjectName("pageSubtitle")
            layout.addWidget(hint)
            self._project_selector.set_selected_project_id(project_id)
        elif candidate and candidate["project_name"]:
            hint = QLabel(f"No existing project matched \"{candidate['project_name']}\" — select or create one below.")
            hint.setObjectName("pageSubtitle")
            layout.addWidget(hint)
        layout.addWidget(self._project_selector)

        layout.addWidget(QLabel("Quotation"))
        if quotation_matches:
            reference, existing_date, existing_total = quotation_matches[0]
            hint = QLabel(
                f"A quotation with reference '{reference}' already exists — current version: "
                f"{format_date(existing_date)}, {format_money(existing_total)}. Adding this as a "
                "revision will be checked against that date/total before it's confirmed."
            )
            hint.setObjectName("pageSubtitle")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self._quotation_combo = QComboBox()
        self._quotation_combo.addItem("New quotation", None)
        self._reload_quotation_options()
        self._project_selector.combo.currentIndexChanged.connect(lambda _i: self._reload_quotation_options())
        layout.addWidget(self._quotation_combo)

        self._layout.addWidget(group)

    def _reload_quotation_options(self) -> None:
        from app.services.quotation_service import list_quotations_for_project

        current = self._quotation_combo.currentData()
        self._quotation_combo.blockSignals(True)
        self._quotation_combo.clear()
        self._quotation_combo.addItem("New quotation", None)
        project_id = self._project_selector.selected_project_id()
        if project_id is not None:
            with session_scope() as session:
                for quotation in list_quotations_for_project(session, project_id):
                    label = quotation.reference_number or quotation.title or f"Quotation #{quotation.id}"
                    self._quotation_combo.addItem(f"Add revision to: {label}", quotation.id)
        if current is not None:
            index = self._quotation_combo.findData(current)
            if index >= 0:
                self._quotation_combo.setCurrentIndex(index)
        self._quotation_combo.blockSignals(False)

    def _build_action_buttons(self) -> None:
        buttons = QHBoxLayout()
        self._confirm_button = QPushButton("Confirm Import")
        self._confirm_button.setObjectName("primaryButton")
        self._confirm_button.clicked.connect(self._open_confirmation)
        self._reject_button = QPushButton("Reject")
        self._reject_button.setObjectName("dangerButton")
        self._reject_button.clicked.connect(self._reject)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        buttons.addWidget(self._confirm_button)
        buttons.addWidget(self._reject_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        self._layout.addLayout(buttons)

    def _current_currency(self) -> str | None:
        return self._currency_combo.currentData() if self._currency_combo is not None else None

    def _disable_editing(self) -> None:
        for widget in self._field_widgets.values():
            widget.setEnabled(False)
        if hasattr(self, "_boq_table"):
            self._boq_table.setEnabled(False)
        if hasattr(self, "_confirm_button"):
            self._confirm_button.setEnabled(False)
            self._reject_button.setEnabled(False)

    # --- Field persistence -----------------------------------------------------

    def _save_field(self, field_name: str, value: object) -> None:
        def _save() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                update_quotation_candidate(session, document, document.quotation_candidate, **{field_name: value})

        run_guarded(self, _save, context=f"editing {field_name}")

    def _save_text_field(self, field_name: str, widget: QLineEdit) -> None:
        self._save_field(field_name, widget.text().strip() or None)

    def _save_date_field(self, field_name: str, widget: QLineEdit) -> None:
        self._save_field(field_name, _parse_date_input(widget.text()))

    def _save_money_field(self, field_name: str, widget: QLineEdit) -> None:
        self._save_field(field_name, _parse_decimal_input(widget.text()))

    def _on_boq_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_boq:
            return
        row = item.row()
        line_id = self._boq_row_ids[row]

        def _save() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                line = next(l for l in document.boq_line_candidates if l.id == line_id)
                update_boq_line_candidate(
                    session,
                    document,
                    line,
                    description=self._boq_table.item(row, 1).text().strip() or None,
                    category_label=self._boq_table.item(row, 2).text().strip() or None,
                    unit=self._boq_table.item(row, 3).text().strip() or None,
                    quantity=_parse_decimal_input(self._boq_table.item(row, 4).text()),
                    unit_rate=_parse_decimal_input(self._boq_table.item(row, 5).text()),
                    extracted_amount=_parse_decimal_input(self._boq_table.item(row, 6).text()),
                )
                return line.calculated_amount, line.amount_flagged

        result = run_guarded(self, _save, context="editing BOQ row")
        if result is None:
            return
        calculated_amount, flagged = result
        self._loading_boq = True
        self._boq_table.item(row, 7).setText(format_money(calculated_amount, None))
        self._boq_table.item(row, 8).setText(AMOUNT_FLAGGED_LABEL if flagged else AMOUNT_OK_LABEL)
        self._loading_boq = False

    # --- Confirm / reject --------------------------------------------------------

    def _open_confirmation(self) -> None:
        dialog = ImportConfirmationDialog(
            self._document_id,
            client_id=self._client_selector.selected_client_id(),
            new_client_name=None,
            project_id=self._project_selector.selected_project_id(),
            quotation_id=self._quotation_combo.currentData(),
            parent=self,
        )
        if dialog.exec():
            self.accept()

    def _reject(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reject import",
            "Reject this import? The staged data is kept for reference, but no business "
            "records will be created from it.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def _do_reject() -> bool:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                reject_import(session, document)
            return True

        if run_guarded(self, _do_reject, context="rejecting import"):
            self.accept()
