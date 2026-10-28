"""The failures images reports deliberately, and their JSON mapping.

Services never import FastAPI, so they raise these and the app-level handler
installed by :func:`install_exception_handlers` renders them. The body is
``{"detail": ...}``, plus ``"code"`` when a client must tell the failure from
another with the same status.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sm_images import constants


class ImagesError(Exception):
    """Base for every deliberate failure."""

    status_code: int = 400
    code: str | None = None

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class NotFound(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 404


class Forbidden(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 403


class Conflict(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 409


class Invalid(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 422


class ServiceUnavailable(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 503


class TenantRequired(Forbidden):
    """A multi-tenant host, and a signed-in request the framework resolved no
    tenant for (no active organisation). Refused rather than guessed; the same
    status and code as pagebuilder's, news' and records' admin refusal."""

    code = constants.TENANT_REQUIRED_CODE


async def _render(_: Request, exc: ImagesError) -> JSONResponse:
    body: dict[str, str] = {"detail": exc.detail}
    if exc.code is not None:
        body["code"] = exc.code
    return JSONResponse(body, status_code=exc.status_code)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ImagesError, _render)  # type: ignore[arg-type]
