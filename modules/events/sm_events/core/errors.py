"""The failures events reports deliberately, and their JSON mapping.

Services never import FastAPI, so they raise these and the app-level handler
installed by :func:`install_exception_handlers` renders them. The body is
``{"detail": ..., "code": ...}``; FastAPI's own request-validation 422 keeps its
standard shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sm_events.core import constants


class EventsError(Exception):
    """Base for every deliberate failure."""

    status_code: int = 400
    code: str = "events_error"
    detail: str = "Events error"

    def __init__(self, detail: str | None = None, code: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        if code is not None:  # else the class default stands
            self.code = code
        super().__init__(self.detail)


class NotFound(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 404
    code = "not_found"
    detail = constants.NOT_FOUND_DETAIL


class Forbidden(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 403
    code = "forbidden"
    detail = "Forbidden"


class OwnerRequired(Forbidden):
    """Visible to the caller, but only the owner or an events manager may do it."""

    code = "owner_required"
    detail = "Only the owner or an events manager can do this"


class TenantRequired(Forbidden):
    """A multi-tenant host, and a signed-in request the framework resolved no
    tenant for (no active organisation). Refused rather than guessed; the same
    status and code as the other modules' admin refusal."""

    code = constants.TENANT_REQUIRED_CODE
    detail = "No organisation is active for this account"


class Conflict(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 409
    code = "conflict"
    detail = "Conflict"


class SlugTaken(Conflict):
    code = "slug_taken"
    detail = constants.SLUG_TAKEN_DETAIL


class Invalid(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 422
    code = "invalid"
    detail = "Invalid"


class UnknownLocale(Invalid):
    code = "unknown_locale"
    detail = constants.UNKNOWN_LOCALE_DETAIL


class ServiceUnavailable(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 503
    code = "service_unavailable"
    detail = "Service unavailable"


def install_exception_handlers(app: FastAPI) -> None:
    """Render every :class:`EventsError` as ``{"detail", "code"}``."""

    @app.exception_handler(EventsError)
    async def _events_error(_request: Request, exc: EventsError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
        )
