"""Turns exceptions into friendly, logged user messages.

No raw Python exception (or traceback) should ever reach a `QMessageBox`.
This module is the single place that decides how each category of error
is presented:

- `ValidationError` (user-correctable input) -> inline/field-level message,
  not logged as an error (it's expected, routine input feedback).
- `SQLAlchemyError` (database problem) -> friendly generic message, full
  detail logged for debugging.
- anything else (unexpected) -> friendly generic message, full detail
  (including traceback) logged for debugging.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from typing import TypeVar

from PySide6.QtWidgets import QMessageBox, QWidget
from sqlalchemy.exc import SQLAlchemyError

from app.services.errors import ValidationError
from app.ui.logging_setup import get_logger

logger = get_logger("ui.errors")

T = TypeVar("T")


def show_validation_error(parent: QWidget | None, message: str) -> None:
    QMessageBox.warning(parent, "Check your entry", message)


def show_database_error(parent: QWidget | None) -> None:
    QMessageBox.critical(
        parent,
        "Something went wrong",
        "A database error occurred and the action could not be completed. "
        "Details have been logged; please try again or contact support if this continues.",
    )


def show_unexpected_error(parent: QWidget | None) -> None:
    QMessageBox.critical(
        parent,
        "Unexpected error",
        "Something unexpected happened and the action could not be completed. "
        "Details have been logged; please try again or contact support if this continues.",
    )


def run_guarded(parent: QWidget | None, action: Callable[[], T], *, context: str) -> T | None:
    """Run `action`, translating any exception into a friendly dialog and a
    log entry, and returning None instead of letting the exception escape
    to the Qt event loop. `context` is a short label (e.g. "creating
    project") used only in the log line, never shown to the user.
    """
    try:
        return action()
    except ValidationError as exc:
        show_validation_error(parent, str(exc))
        return None
    except SQLAlchemyError:
        logger.exception("Database error while %s", context)
        show_database_error(parent)
        return None
    except Exception:
        logger.exception("Unexpected error while %s", context)
        show_unexpected_error(parent)
        return None


@contextmanager
def guard(parent: QWidget | None, *, context: str):
    """Context-manager form of `run_guarded`, for call sites that don't fit
    a single expression (e.g. a block that both writes to the DB and then
    refreshes a widget)."""
    try:
        yield
    except ValidationError as exc:
        show_validation_error(parent, str(exc))
    except SQLAlchemyError:
        logger.exception("Database error while %s", context)
        show_database_error(parent)
    except Exception:
        logger.exception("Unexpected error while %s", context)
        show_unexpected_error(parent)
