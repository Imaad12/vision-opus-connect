"""Generic Review Queue: the human operating layer for document ingestion.

This page is built entirely on top of `app.services.review_service`'s
existing `ReviewItem`/`QuotationReviewQueue`/`ClientAwardEvidenceReviewQueue`
triage — it never recomputes a confidence status, a match status, or any
other review outcome itself. Its only two jobs are: render what
`review_service.py` already decided (split into "Needs Attention" and
"Ready to Confirm"), and dispatch a click to whichever existing detail
workflow already handles that document kind.

Deliberately document-kind agnostic: `_QUEUE_SOURCES` is the one place a
new document kind (vendor invoices, supplier documents, expense
documents, ...) gets registered, once that kind has its own
`review_service.list_x_review_queue` function — one new `_QueueSource`
entry, with its own `open_item` dispatcher. Nothing else on this page
(filtering, counts, the table, refresh) changes when a new kind is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.enums import SegmentReviewStatus
from app.database.session import session_scope
from app.services.import_service import get_imported_document
from app.services.review_service import (
    ReviewItem,
    list_client_award_evidence_review_queue,
    list_quotation_review_queue,
)
from app.ui.imports.import_review_dialog import ImportReviewDialog
from app.ui.imports.segment_boundary_review_dialog import SegmentBoundaryReviewDialog
from app.ui.style import FAVORABLE, UNFAVORABLE
from app.ui.widgets.status_badge import Badge

_NEEDS_ATTENTION = "Needs Attention"
_READY_TO_CONFIRM = "Ready to Confirm"
_ALL_STATUSES = "All"


def _open_quotation_review_item(parent: QWidget, item: ReviewItem) -> None:
    """Route a quotation-queue item to the existing workflow that already
    handles it: a still-unresolved segment boundary (no locked candidate
    to review yet) opens the boundary hub, exactly like `ImportsPage`
    does for any segmented document; anything else — a non-segmented
    document, or an already-locked segment — opens the existing
    quotation review dialog directly, the same way
    `SegmentBoundaryReviewDialog` itself opens it for one locked segment.
    This only *reads* the segment's current status to decide which
    already-existing dialog to open — it does not evaluate confidence,
    matching, or anything `review_service.py` already decided.
    """
    if item.segment_id is None:
        ImportReviewDialog(item.document_id, parent).exec()
        return

    with session_scope() as session:
        document = get_imported_document(session, item.document_id)
        segment = next((s for s in document.segments if s.id == item.segment_id), None) if document else None
        boundary_unresolved = segment is not None and segment.review_status in (
            SegmentReviewStatus.PROPOSED,
            SegmentReviewStatus.ACCEPTED,
        )

    if boundary_unresolved:
        SegmentBoundaryReviewDialog(item.document_id, parent).exec()
    else:
        ImportReviewDialog(item.document_id, parent, segment_id=item.segment_id).exec()


def _open_client_award_evidence_review_item(parent: QWidget, item: ReviewItem) -> None:
    """Routing placeholder only. The Purchase Order review dialog does not
    exist yet — this deliberately does not open, fake, or partially
    implement a PO review workflow (no confirm/reject action is offered
    here); it only tells the reviewer plainly that the screen isn't built
    yet, so nothing here can be mistaken for a real review outcome."""
    QMessageBox.information(
        parent,
        "Purchase Order review not yet available",
        f"'{item.filename}' is staged and ready to be reviewed as a Purchase Order, but the "
        "Purchase Order review screen has not been built yet.",
    )


@dataclass(frozen=True, slots=True)
class _QueueSource:
    key: str
    label: str
    fetch_queue: Callable[..., object]
    open_item: Callable[[QWidget, ReviewItem], None]


_QUEUE_SOURCES: list[_QueueSource] = [
    _QueueSource("quotation", "Quotation", list_quotation_review_queue, _open_quotation_review_item),
    _QueueSource(
        "client_award_evidence", "Purchase Order", list_client_award_evidence_review_queue, _open_client_award_evidence_review_item
    ),
]


@dataclass(frozen=True, slots=True)
class _Row:
    source: _QueueSource
    status: str
    item: ReviewItem


class ReviewQueuePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[_Row] = []
        self._visible_rows: list[_Row] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Review Queue")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Everything staged from a document that still needs a human decision, split by "
            "whether it needs attention or is simply waiting for a confirm click."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Type"))
        self._kind_filter = QComboBox()
        self._kind_filter.addItem("All types", None)
        for source in _QUEUE_SOURCES:
            self._kind_filter.addItem(source.label, source.key)
        self._kind_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._kind_filter)

        toolbar.addWidget(QLabel("Status"))
        self._status_filter = QComboBox()
        self._status_filter.addItem(_ALL_STATUSES)
        self._status_filter.addItem(_NEEDS_ATTENTION)
        self._status_filter.addItem(_READY_TO_CONFIRM)
        self._status_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._status_filter)

        toolbar.addStretch(1)
        self._summary_label = QLabel()
        self._summary_label.setObjectName("pageSubtitle")
        toolbar.addWidget(self._summary_label)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_button)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Status", "Type", "Filename", "Pages", "Reason", ""])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.cellDoubleClicked.connect(lambda row, _col: self._open_row(row))
        layout.addWidget(self._table, 1)

        self.refresh()

    def refresh(self) -> None:
        self._rows = []
        with session_scope() as session:
            for source in _QUEUE_SOURCES:
                queue = source.fetch_queue(session)
                for item in queue.needs_attention:
                    self._rows.append(_Row(source, _NEEDS_ATTENTION, item))
                for item in queue.ready_to_confirm:
                    self._rows.append(_Row(source, _READY_TO_CONFIRM, item))
        self._apply_filters()

    def _apply_filters(self) -> None:
        kind_key = self._kind_filter.currentData()
        status = self._status_filter.currentText()

        self._visible_rows = [
            row
            for row in self._rows
            if (kind_key is None or row.source.key == kind_key)
            and (status == _ALL_STATUSES or row.status == status)
        ]

        needs_attention_count = sum(1 for row in self._rows if row.status == _NEEDS_ATTENTION)
        ready_count = sum(1 for row in self._rows if row.status == _READY_TO_CONFIRM)
        self._summary_label.setText(f"{needs_attention_count} needs attention · {ready_count} ready to confirm")

        self._table.setRowCount(len(self._visible_rows))
        for row_index, row in enumerate(self._visible_rows):
            self._table.setCellWidget(
                row_index, 0, Badge(row.status, FAVORABLE if row.status == _READY_TO_CONFIRM else UNFAVORABLE)
            )
            self._table.setItem(row_index, 1, QTableWidgetItem(row.source.label))
            self._table.setItem(row_index, 2, QTableWidgetItem(row.item.filename))
            self._table.setItem(row_index, 3, QTableWidgetItem(row.item.segment_pages or ""))
            self._table.setItem(row_index, 4, QTableWidgetItem(row.item.reason))
            open_button = QPushButton("Open")
            open_button.clicked.connect(lambda _checked=False, r=row: self._open_row_data(r))
            self._table.setCellWidget(row_index, 5, open_button)

    def _open_row(self, row_index: int) -> None:
        if 0 <= row_index < len(self._visible_rows):
            self._open_row_data(self._visible_rows[row_index])

    def _open_row_data(self, row: _Row) -> None:
        row.source.open_item(self, row.item)
        self.refresh()
