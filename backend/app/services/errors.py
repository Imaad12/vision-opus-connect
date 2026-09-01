"""Shared service-layer exceptions.

`ValidationError` marks a user-correctable input problem (bad/missing
field, business-rule violation) as distinct from a database or unexpected
system error. The UI layer catches this specifically to show a
field-level or inline message, and lets everything else fall through to
the generic error handler — see `app/ui/errors.py`.
"""

from __future__ import annotations


class ValidationError(ValueError):
    """Raised by service-layer functions for user-correctable input problems."""


class RevisionConflictError(ValidationError):
    """Raised by `import_service.confirm_import` when an incoming quotation
    revision's date conflicts with the target quotation's current version
    (same reference, but an earlier date, or the same date with a
    materially different total) and the caller has not explicitly
    acknowledged the conflict.

    A subclass of `ValidationError` so any code that only knows about the
    generic type still handles it safely (shows a message, blocks the
    action) — code that wants to offer a "review and proceed anyway" flow
    can catch this specifically instead. The structured fields let a UI
    render a clear side-by-side comparison rather than parsing the message
    text.
    """

    def __init__(
        self,
        message: str,
        *,
        conflict_type: str,
        reference,
        incoming_date,
        incoming_total,
        existing_date,
        existing_total,
    ) -> None:
        super().__init__(message)
        self.conflict_type = conflict_type
        self.reference = reference
        self.incoming_date = incoming_date
        self.incoming_total = incoming_total
        self.existing_date = existing_date
        self.existing_total = existing_total
