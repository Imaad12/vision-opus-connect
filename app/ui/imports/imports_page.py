"""Import Center: pick local files, see every staged import and its
status, and open one for review. This page never extracts or interprets
document content itself — it only calls `app.services.import_service` and
displays what comes back (see UI_ARCHITECTURE.md for the import pipeline).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.session import session_scope
from app.services.import_service import (
    check_for_duplicate,
    get_imported_document,
    list_imported_documents,
    stage_document,
)
from app.ui.errors import run_guarded
from app.ui.formatting import format_date
from app.ui.imports.import_review_dialog import ImportReviewDialog
from app.ui.imports.segment_boundary_review_dialog import SegmentBoundaryReviewDialog
from app.ui.widgets.sortable_items import ValueSortItem

_FILE_FILTER = (
    "Supported documents (*.pdf *.xlsx *.xlsm *.xlsb *.xls *.docx *.doc *.csv *.txt "
    "*.png *.jpg *.jpeg *.tif *.tiff);;All files (*)"
)

_STATUS_LABELS = {
    "PENDING": "Pending",
    "EXTRACTING": "Extracting",
    "EXTRACTION_COMPLETE": "Extraction Complete",
    "FAILED": "Failed",
    "UNSUPPORTED": "Unsupported",
    "OCR_REQUIRED": "OCR Required",
    "MULTIPLE_QUOTATIONS_DETECTED": "Multiple Quotations Found",
    "SEGMENTS_PROPOSED": "Boundaries Proposed",
}

_REVIEW_STATUS_LABELS = {
    "NEEDS_REVIEW": "Needs Review",
    "CONFIRMED": "Confirmed",
    "REJECTED": "Rejected",
}


class ImportsPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Import Center")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Import local quotation/BOQ files, review what was extracted, and confirm before "
            "anything is added to the business database."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        import_button = QPushButton("Import Documents")
        import_button.setObjectName("primaryButton")
        import_button.clicked.connect(self._import_documents)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by filename...")
        self._search.textChanged.connect(self.refresh)
        toolbar.addWidget(import_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self._search)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Filename", "Type", "Imported", "Extraction", "Review", ""]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.cellDoubleClicked.connect(lambda row, _col: self._open_review(row))
        layout.addWidget(self._table, 1)

        self.refresh()

    def refresh(self) -> None:
        search = self._search.text().strip() or None
        with session_scope() as session:
            documents = list_imported_documents(session, search=search)
            rows = [
                (
                    document.id,
                    document.filename,
                    document.extension.upper(),
                    document.created_at,
                    _STATUS_LABELS.get(document.extraction_status.value, document.extraction_status.value),
                    _REVIEW_STATUS_LABELS.get(document.review_status.value, document.review_status.value),
                )
                for document in documents
            ]

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row_index, (document_id, filename, extension, imported_at, extraction_label, review_label) in enumerate(
            rows
        ):
            filename_item = QTableWidgetItem(filename)
            filename_item.setData(1000, document_id)
            self._table.setItem(row_index, 0, filename_item)
            self._table.setItem(row_index, 1, QTableWidgetItem(extension))
            self._table.setItem(row_index, 2, ValueSortItem(format_date(imported_at), imported_at))
            self._table.setItem(row_index, 3, QTableWidgetItem(extraction_label))
            self._table.setItem(row_index, 4, QTableWidgetItem(review_label))
            open_button = QPushButton("Review")
            open_button.clicked.connect(lambda _checked=False, doc_id=document_id: self._open_review_by_id(doc_id))
            self._table.setCellWidget(row_index, 5, open_button)
        self._table.setSortingEnabled(True)

    def _open_review(self, row: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        self._open_review_by_id(item.data(1000))

    def _open_review_by_id(self, document_id: int) -> None:
        with session_scope() as session:
            document = get_imported_document(session, document_id)
            has_segments = bool(document and document.segments)

        # A sequentially segmented document (see IMPORT_ARCHITECTURE.md)
        # always opens the boundary-review hub first, even once every
        # segment is locked/confirmed -- it's the natural place to see and
        # re-open each segment's own quotation review. A document that was
        # never segmented (deterministic imports, and OCR scans with no
        # page structure to segment) opens the original single-candidate
        # review dialog unchanged.
        if has_segments:
            dialog = SegmentBoundaryReviewDialog(document_id, self)
        else:
            dialog = ImportReviewDialog(document_id, self)
        dialog.exec()
        self.refresh()

    def _import_documents(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import Documents", "", _FILE_FILTER)
        if not paths:
            return

        for raw_path in paths:
            path = Path(raw_path)
            allow_duplicate = False

            with session_scope() as session:
                existing = check_for_duplicate(session, path)
            if existing is not None:
                reply = QMessageBox.question(
                    self,
                    "Already imported",
                    f"'{path.name}' appears to already have been imported on "
                    f"{format_date(existing.created_at)} as '{existing.filename}' "
                    f"(staging record #{existing.id}).\n\nImport it again anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    continue
                allow_duplicate = True

            def _stage(p: Path = path, ad: bool = allow_duplicate) -> None:
                with session_scope() as session:
                    stage_document(session, p, allow_duplicate=ad)

            run_guarded(self, _stage, context=f"importing {path.name}")

        self.refresh()
