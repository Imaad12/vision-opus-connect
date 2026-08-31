"""Structured per-request access logging.

Isolated from the CORS/error-handling wiring in `app/api/main.py` since
it's an operational concern (what happened, how long it took) rather than
part of the API's request/response contract.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.timing import get_request_timing, start_request_timing

logger = logging.getLogger("app.api.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_request_timing()
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        # Phase breakdown (app.api.timing): auth = JWT verification,
        # rbac = Supabase can() check (cache misses only -- a hit costs
        # effectively nothing and correctly doesn't show up here), db =
        # every SQL statement's round trip, summed. "other" is
        # everything not captured above -- routing, dependency
        # resolution, Pydantic serialization, this middleware's own
        # overhead -- deliberately not broken down further since
        # isolating e.g. serialization specifically would mean
        # instrumenting FastAPI's response-rendering internals, a much
        # more invasive change for a number that's expected to be small.
        phases = get_request_timing()
        auth_ms = phases.get("auth", 0.0) * 1000
        rbac_ms = phases.get("rbac", 0.0) * 1000
        db_ms = phases.get("db", 0.0) * 1000
        other_ms = max(0.0, duration_ms - auth_ms - rbac_ms - db_ms)

        logger.info(
            "%s %s -> %d (%.1fms total, auth=%.1fms rbac=%.1fms db=%.1fms other=%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            auth_ms,
            rbac_ms,
            db_ms,
            other_ms,
        )
        return response
