"""The failures newsletter reports deliberately, and their JSON mapping.

Services never import FastAPI, so they raise these and the app-level handler
installed by :func:`install_exception_handlers` renders them. The body is
``{"detail": ..., "code": ...}``.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sm_newsletter.core import constants


class NewsletterError(Exception):
    """Base for every deliberate failure."""

    status: int = 400
    code: str = "newsletter_error"
    detail: str = "Newsletter error"

    def __init__(self, detail: str | None = None, code: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        if code is not None:  # else the class default stands
            self.code = code
        super().__init__(self.detail)


class NotFound(NewsletterError):  # noqa: N818 - HTTP vocabulary, deliberately
    status = 404
    code = "not_found"
    detail = constants.NOT_FOUND_DETAIL


class Forbidden(NewsletterError):  # noqa: N818 - HTTP vocabulary, deliberately
    status = 403
    code = "forbidden"
    detail = "Forbidden"


class TenantRequired(Forbidden):
    """A multi-tenant host, and a signed-in request the framework resolved no
    tenant for (no active organisation). Refused rather than guessed; the same
    status and code as the other modules' admin refusal."""

    code = constants.TENANT_REQUIRED_CODE
    detail = "No organisation is active for this account"


class SmtpPasswordUnreadable(NewsletterError):  # noqa: N818 - names the failure, not an *Error
    """The stored SMTP password cannot be decrypted (the key changed)."""

    status = 500
    code = "smtp_password_unreadable"
    detail = "The stored SMTP password cannot be read; enter it again"


class InvalidPassword(NewsletterError):  # noqa: N818 - names the field
    """A blank or oversized SMTP password; the detail never repeats the value."""

    status = 422
    code = "invalid_password"
    detail = "The password must be 1 to 1024 characters and not blank"


async def render(request: Request, exc: NewsletterError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NewsletterError, render)  # type: ignore[arg-type]
