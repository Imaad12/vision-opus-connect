"""Sequential quotation boundary review (segmentation).

Shown for an OCR'd document whose pages were split into proposed
quotation segments (`ExtractionStatus.SEGMENTS_PROPOSED` — see
`app.core.import_segmentation` and IMPORT_ARCHITECTURE.md's sequential
segmentation section). No segment's boundary — including a
HIGH-confidence one — becomes final without an explicit action here:
Accept, Split, Merge, or Exclude. Only once every segment is resolved can
"Lock Segments" run extraction, restricted to each segment's own accepted
page range (`app.services.import_service.lock_segments`).

This dialog never extracts a financial value itself and never writes a
business record — it only edits `ImportedDocumentSegment` boundaries via
`app.services.import_service` and, once locked, hands off to the existing,
unmodified `ImportReviewDialog` (opened per segment) for the actual
quotation-candidate review/confirm/reject flow.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.enums import ConfidenceLevel, ExtractionStatus, SegmentReviewStatus
from app.database.session import session_scope
from app.services.import_service import (
    accept_segment,
    exclude_segment,
    get_imported_document,
    get_segment,
    lock_segments,
    merge_segments,
    move_segment_boundary,
    split_segment,
)
from app.ui.confidence_labels import CONFIDENCE_COLORS, CONFIDENCE_LABELS
from app.ui.errors import run_guarded
from app.ui.formatting import format_date
from app.ui.style import FAVORABLE, INK_MUTED, UNFAVORABLE
from app.ui.widgets.status_badge import Badge

_THUMBNAIL_DPI = 40  # deliberately small -- a boundary-review aid, not a document viewer
_MAX_THUMBNAILS_PER_SEGMENT = 8

_SEGMENT_STATUS_LABELS = {
    SegmentReviewStatus.PROPOSED: "Awaiting review",
    SegmentReviewStatus.ACCEPTED: "Accepted — not yet locked",
    SegmentReviewStatus.LOCKED: "Locked",
    SegmentReviewStatus.CONFIRMED: "Confirmed",
    SegmentReviewStatus.REJECTED: "Rejected",
    SegmentReviewStatus.EXCLUDED_NOT_A_QUOTATION: "Excluded (not a quotation)",
}

_SEGMENT_STATUS_COLORS = {
    SegmentReviewStatus.PROPOSED: INK_MUTED,
    SegmentReviewStatus.ACCEPTED: FAVORABLE,
    SegmentReviewStatus.LOCKED: FAVORABLE,
    SegmentReviewStatus.CONFIRMED: FAVORABLE,
    SegmentReviewStatus.REJECTED: UNFAVORABLE,
    SegmentReviewStatus.EXCLUDED_NOT_A_QUOTATION: INK_MUTED,
}


def _render_page_thumbnails(original_path: str, start_page: int, end_page: int) -> list[tuple[int, QPixmap]]:
    """Best-effort small page previews rendered directly from the source
    file (independent of the OCR pipeline — this never re-runs OCR or
    touches `raw_extracted_data`). Returns an empty list for anything that
    can't be rendered (missing file, non-PDF image scan, corrupt page) —
    the boundary screen still works from page numbers and detected
    fields alone; thumbnails are a convenience, not a requirement."""
    path = Path(original_path)
    if not path.exists() or path.suffix.lower() != ".pdf":
        return []
    thumbnails: list[tuple[int, QPixmap]] = []
    try:
        import pymupdf

        document = pymupdf.open(path)
        try:
            last_page = min(end_page, start_page + _MAX_THUMBNAILS_PER_SEGMENT - 1)
            for page_number in range(start_page, last_page + 1):
                page_index = page_number - 1
                if page_index < 0 or page_index >= document.page_count:
                    continue
                pixmap = document.load_page(page_index).get_pixmap(dpi=_THUMBNAIL_DPI)
                image_bytes = pixmap.tobytes("png")
                qpixmap = QPixmap()
                if qpixmap.loadFromData(image_bytes, "PNG"):
                    thumbnails.append((page_number, qpixmap))
        finally:
            document.close()
    except Exception:  # noqa: BLE001 -- a rendering failure must never block boundary review
        return thumbnails
    return thumbnails


class SegmentBoundaryReviewDialog(QDialog):
    def __init__(self, document_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._document_id = document_id
        self.setWindowTitle("Review Quotation Boundaries")
        self.setMinimumSize(920, 700)

        outer = QVBoxLayout(self)
        title = QLabel("Sequential Quotation Boundaries")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "This scan was split into the proposed quotation segments below. Review each one — "
            "accept, move, split, merge, or exclude — before it can be extracted. No boundary, "
            "including a high-confidence one, becomes final on its own."
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        outer.addWidget(self._scroll, 1)

        buttons = QHBoxLayout()
        self._lock_button = QPushButton("Lock Segments")
        self._lock_button.setObjectName("primaryButton")
        self._lock_button.clicked.connect(self._lock_all)
        buttons.addWidget(self._lock_button)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        outer.addLayout(buttons)

        self._reload()

    # --- Loading -------------------------------------------------------------

    def _reload(self) -> None:
        with session_scope() as session:
            document = get_imported_document(session, self._document_id)
            if document is None:
                self._set_body(QLabel("This staged import no longer exists."))
                return
            self._original_path = document.original_path
            self._is_segmented_status = document.extraction_status in (
                ExtractionStatus.SEGMENTS_PROPOSED,
                ExtractionStatus.EXTRACTION_COMPLETE,
            )
            segments = [
                {
                    "id": s.id,
                    "segment_order": s.segment_order,
                    "start_page": s.start_page,
                    "end_page": s.end_page,
                    "boundary_confidence": s.boundary_confidence,
                    "boundary_signals": s.boundary_signals,
                    "detected_quotation_number": s.detected_quotation_number,
                    "detected_quotation_date": s.detected_quotation_date,
                    "review_status": s.review_status,
                    "reviewer_adjusted": s.reviewer_adjusted,
                    "has_candidate": s.quotation_candidate is not None,
                }
                for s in sorted(document.segments, key=lambda s: s.segment_order)
            ]

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        if not segments:
            layout.addWidget(QLabel("No segments have been proposed for this document."))
        for index, segment in enumerate(segments):
            layout.addWidget(self._build_segment_group(segment, is_last=(index == len(segments) - 1)))
        layout.addStretch(1)
        self._set_body(body)

        all_resolved = bool(segments) and all(
            s["review_status"] != SegmentReviewStatus.PROPOSED for s in segments
        )
        already_locked = bool(segments) and all(
            s["review_status"] not in (SegmentReviewStatus.PROPOSED, SegmentReviewStatus.ACCEPTED)
            for s in segments
        )
        self._lock_button.setEnabled(all_resolved and not already_locked)

    def _set_body(self, widget: QWidget) -> None:
        self._scroll.setWidget(widget)

    def _build_segment_group(self, segment: dict, *, is_last: bool) -> QGroupBox:
        status = segment["review_status"]
        group = QGroupBox(f"Segment #{segment['segment_order']} — pages {segment['start_page']}-{segment['end_page']}")
        layout = QVBoxLayout(group)

        header = QHBoxLayout()
        confidence_value = segment["boundary_confidence"]
        if confidence_value:
            try:
                level = ConfidenceLevel(confidence_value)
                header.addWidget(Badge(CONFIDENCE_LABELS[level], CONFIDENCE_COLORS[level]))
            except ValueError:
                pass
        header.addWidget(Badge(_SEGMENT_STATUS_LABELS.get(status, status.value), _SEGMENT_STATUS_COLORS.get(status, INK_MUTED)))
        if segment["reviewer_adjusted"]:
            header.addWidget(Badge("Reviewer-adjusted", INK_MUTED))
        header.addStretch(1)
        layout.addLayout(header)

        detected = QLabel(
            f"Detected reference: {segment['detected_quotation_number'] or '(none found)'}   |   "
            f"Detected date: {format_date(segment['detected_quotation_date']) if segment['detected_quotation_date'] else '(none found)'}"
        )
        layout.addWidget(detected)

        if segment["boundary_signals"]:
            signals = QLabel(segment["boundary_signals"].replace("\n", " "))
            signals.setWordWrap(True)
            signals.setObjectName("pageSubtitle")
            layout.addWidget(signals)

        thumbnails = _render_page_thumbnails(self._original_path, segment["start_page"], segment["end_page"])
        if thumbnails:
            strip = QHBoxLayout()
            for page_number, pixmap in thumbnails:
                cell = QVBoxLayout()
                image_label = QLabel()
                image_label.setPixmap(pixmap.scaledToHeight(90, Qt.SmoothTransformation))
                image_label.setFrameShape(QFrame.Box)
                cell.addWidget(image_label)
                cell.addWidget(QLabel(f"p.{page_number}", alignment=Qt.AlignHCenter))
                cell_widget = QWidget()
                cell_widget.setLayout(cell)
                strip.addWidget(cell_widget)
            if segment["end_page"] - segment["start_page"] + 1 > _MAX_THUMBNAILS_PER_SEGMENT:
                strip.addWidget(QLabel("…"))
            strip.addStretch(1)
            layout.addLayout(strip)

        actions = QHBoxLayout()
        editable = status == SegmentReviewStatus.PROPOSED

        accept_button = QPushButton("Accept Boundary")
        accept_button.setEnabled(editable)
        accept_button.clicked.connect(lambda _c=False, sid=segment["id"]: self._accept(sid))
        actions.addWidget(accept_button)

        exclude_button = QPushButton("Exclude (Not a Quotation)")
        exclude_button.setEnabled(status in (SegmentReviewStatus.PROPOSED, SegmentReviewStatus.ACCEPTED, SegmentReviewStatus.LOCKED))
        exclude_button.clicked.connect(lambda _c=False, sid=segment["id"]: self._exclude(sid))
        actions.addWidget(exclude_button)

        can_edit_boundary = status in (
            SegmentReviewStatus.PROPOSED,
            SegmentReviewStatus.ACCEPTED,
            SegmentReviewStatus.LOCKED,
        )

        if segment["start_page"] < segment["end_page"] and can_edit_boundary:
            split_spin = QSpinBox()
            split_spin.setRange(segment["start_page"], segment["end_page"] - 1)
            split_spin.setValue(segment["start_page"])
            split_button = QPushButton("Split After Page")
            split_button.clicked.connect(
                lambda _c=False, sid=segment["id"], spin=split_spin: self._split(sid, spin.value())
            )
            actions.addWidget(split_spin)
            actions.addWidget(split_button)

        if not is_last and can_edit_boundary:
            merge_button = QPushButton("Merge With Next Segment")
            merge_button.clicked.connect(lambda _c=False, sid=segment["id"]: self._merge(sid))
            actions.addWidget(merge_button)

            move_spin = QSpinBox()
            move_spin.setRange(segment["start_page"], segment["end_page"])
            move_spin.setValue(segment["end_page"])
            move_button = QPushButton("Move Boundary To End Of Page")
            move_button.clicked.connect(
                lambda _c=False, sid=segment["id"], spin=move_spin: self._move(sid, spin.value())
            )
            actions.addWidget(move_spin)
            actions.addWidget(move_button)

        actions.addStretch(1)
        layout.addLayout(actions)

        if status == SegmentReviewStatus.LOCKED and not segment["has_candidate"]:
            warning = QLabel(
                "⚠ This segment still looks like it contains more than one quotation after locking "
                "— no candidate was created. Split it further and lock again."
            )
            warning.setWordWrap(True)
            warning.setObjectName("dangerButton")
            layout.addWidget(warning)
        elif status == SegmentReviewStatus.LOCKED and segment["has_candidate"]:
            review_button = QPushButton("Review This Quotation")
            review_button.clicked.connect(lambda _c=False, sid=segment["id"]: self._open_segment_review(sid))
            layout.addWidget(review_button)
        elif status in (SegmentReviewStatus.CONFIRMED, SegmentReviewStatus.REJECTED):
            review_button = QPushButton("View This Quotation")
            review_button.clicked.connect(lambda _c=False, sid=segment["id"]: self._open_segment_review(sid))
            layout.addWidget(review_button)

        return group

    # --- Actions ---------------------------------------------------------------

    def _accept(self, segment_id: int) -> None:
        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = get_segment(session, segment_id)
                accept_segment(session, document, segment)

        if run_guarded(self, _do, context="accepting segment boundary") is not None or True:
            self._reload()

    def _exclude(self, segment_id: int) -> None:
        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = get_segment(session, segment_id)
                exclude_segment(session, document, segment)

        run_guarded(self, _do, context="excluding segment")
        self._reload()

    def _split(self, segment_id: int, split_after_page: int) -> None:
        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = get_segment(session, segment_id)
                split_segment(session, document, segment, split_after_page=split_after_page)

        run_guarded(self, _do, context="splitting segment")
        self._reload()

    def _merge(self, segment_id: int) -> None:
        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = get_segment(session, segment_id)
                segments = sorted(document.segments, key=lambda s: s.segment_order)
                index = next(i for i, s in enumerate(segments) if s.id == segment.id)
                next_segment = segments[index + 1]
                merge_segments(session, document, segment, next_segment)

        run_guarded(self, _do, context="merging segments")
        self._reload()

    def _move(self, segment_id: int, new_end_page: int) -> None:
        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                segment = get_segment(session, segment_id)
                move_segment_boundary(session, document, segment, new_end_page=new_end_page)

        run_guarded(self, _do, context="moving segment boundary")
        self._reload()

    def _lock_all(self) -> None:
        reply = QMessageBox.question(
            self,
            "Lock segments",
            "Lock this boundary layout? Each accepted segment will be extracted from its own pages "
            "only. You can still review, edit, confirm, or reject each resulting quotation "
            "afterwards, but boundaries cannot be changed once a segment is confirmed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def _do() -> None:
            with session_scope() as session:
                document = get_imported_document(session, self._document_id)
                lock_segments(session, document)

        run_guarded(self, _do, context="locking segments")
        self._reload()

    def _open_segment_review(self, segment_id: int) -> None:
        from app.ui.imports.import_review_dialog import ImportReviewDialog

        dialog = ImportReviewDialog(self._document_id, self, segment_id=segment_id)
        dialog.exec()
        self._reload()
