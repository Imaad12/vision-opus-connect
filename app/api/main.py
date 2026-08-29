"""FastAPI application factory.

This is the one new runtime surface this backend exposes: everything it
serves is a thin translation of the existing `app/services/*` layer into
HTTP. No business rule is decided in this package -- a route that needs
one calls the service function that already owns it, exactly as the
PySide6 UI does. See API_ARCHITECTURE.md for the full design.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import (
    clients,
    company,
    contacts,
    contracts,
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
    vendors,
)
from app.core.config import settings
from app.services.errors import ValidationError


def create_app() -> FastAPI:
    app = FastAPI(title="Vision Contracting API", version="0.1.0")

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

    app.include_router(health.router)
    app.include_router(company.router)
    app.include_router(clients.router)
    app.include_router(vendors.router)
    app.include_router(projects.router)
    app.include_router(quotations.router)
    app.include_router(contracts.router)
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

    return app


app = create_app()
