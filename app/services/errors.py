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
