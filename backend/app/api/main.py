"""FastAPI application factory.

This is the one new runtime surface this backend exposes: everything it
serves is a thin translation of the existing `app/services/*` layer into
HTTP. No business rule is decided in this package -- a route that needs
one calls the service function that already owns it, exactly as the
PySide6 UI does. See API_ARCHITECTURE.md for the full design.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.auth import SupabaseUnavailableError
from app.api.logging_middleware import AccessLogMiddleware
from app.api.routers import (
    clients,
    company,
    contacts,
    contracts,
    dashboard,
    employees,
    expenses,
    health,
    invoices,
    leads,
    lookups,
    management,
    payments,
    payroll,
    projects,
    purchase_orders,
    purchase_requests,
    quotations,
    receipts,
    users,
    vendors,
)
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.services.errors import ValidationError


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Vision Contracting API", version="0.1.0")
    app.add_middleware(AccessLogMiddleware)

    # Without this, every cross-origin request from the frontend (a
    # different origin/port than this API) fails the browser's CORS
    # preflight -- no Access-Control-Allow-Origin header means the
    # browser blocks the real request and it surfaces to the frontend as
    # a bare "Failed to fetch", not an HTTP error with a status code.
    # `allow_credentials=False` because this API is never sent cookies --
    # the frontend forwards the Supabase session as an Authorization
    # header (see src/lib/api.ts in the frontend repo), which needs no
    # credentialed-CORS mode at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(ValidationError)
    def _handle_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
        # Belt-and-braces: routes already catch ValidationError and return
        # 422 with context, but a service call reached from a future route
        # without that try/except must still fail as a client error, never
        # as an unhandled 500.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(SupabaseUnavailableError)
    def _handle_supabase_unavailable(_request: Request, exc: SupabaseUnavailableError) -> JSONResponse:
        # Global, not per-route: every SupabaseAdmin-backed route (create
        # user, reset password, role/scope/employee-link changes) can hit
        # this the same way -- Supabase itself unreachable (DNS/TLS/
        # timeout/connection refused), not a validation problem. 503
        # (not 500): the request was well-formed and the caller was
        # authorized, but a required upstream dependency didn't respond,
        # which is the textbook case for "Service Unavailable" and tells
        # the client this is worth retrying rather than a bug to report.
        logging.getLogger("app.api").warning("Supabase unavailable: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "The identity provider is temporarily unavailable. Please try again shortly."},
        )

    @app.exception_handler(IntegrityError)
    def _handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        # Belt-and-braces for the theoretical race a service-layer
        # existence/uniqueness check can't fully close (two concurrent
        # requests both pass the pre-check, then only the database's own
        # unique constraint -- app_users.username, app_users.employee_id --
        # catches the second one). 409 (Conflict), not 500: the request
        # was well-formed, but it collided with another one that got
        # there first. Never echoes the raw database error (could name
        # internal table/column details) -- just says what happened.
        logging.getLogger("app.api").warning("Integrity error: %s", exc)
        return JSONResponse(
            status_code=409,
            content={"detail": "This conflicts with an existing record (e.g. a duplicate username or link)."},
        )

    @app.exception_handler(Exception)
    def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Last resort: anything not already caught by a route's own
        # try/except or the handlers above. Logged server-side with the
        # real exception (never in the response body) so an operator can
        # diagnose it from Render's logs, while the client only ever sees
        # a generic message -- no stack trace, no internal detail, and
        # certainly never a secret (service-role key, tokens, passwords),
        # regardless of what the underlying exception's message contained.
        logging.getLogger("app.api").exception(
            "Unhandled exception on %s %s", request.method, request.url.path
        )
        return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})

    app.include_router(health.router)
    app.include_router(company.router)
    app.include_router(clients.router)
    app.include_router(vendors.router)
    app.include_router(projects.router)
    app.include_router(quotations.router)
    app.include_router(contracts.router)
    app.include_router(dashboard.router)
    app.include_router(purchase_requests.router)
    app.include_router(purchase_orders.router)
    app.include_router(receipts.router)
    app.include_router(lookups.router)
    app.include_router(invoices.router)
    app.include_router(payments.router)
    app.include_router(expenses.router)
    app.include_router(contacts.router)
    app.include_router(leads.router)
    app.include_router(employees.router)
    app.include_router(payroll.router)
    app.include_router(management.router)
    app.include_router(users.router)

    return app


app = create_app()
