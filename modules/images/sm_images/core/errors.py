"""The failures images reports deliberately, and their JSON mapping.

Services never import FastAPI, so they raise these and the app-level handler
installed by :func:`install_exception_handlers` renders them. The body is
``{"detail": ...}``, plus ``"code"`` when a client must tell the failure from
another with the same status.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from sm_images.core import constants


class ImagesError(Exception):
    """Base for every deliberate failure."""

    status_code: int = 400
    code: str | None = None

    def __init__(self, detail: str, code: str | None = None) -> None:
        self.detail = detail
        super().__init__(detail)
        if code is not None:  # else the class default stands
            self.code = code


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


class UnsupportedType(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """The bytes are not an image type images accepts (sniffed, never the name)."""

    status_code = 415
    code = constants.CODE_UNSUPPORTED_TYPE


class ImageTooLarge(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """More pixels than Pillow's ``Image.MAX_IMAGE_PIXELS``: a decompression-bomb
    candidate, refused before anything is stored (pagebuilder #221)."""

    status_code = 413
    code = constants.CODE_TOO_MANY_PIXELS


class FileTooLarge(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 413
    code = constants.CODE_FILE_TOO_LARGE


class UseDirectUpload(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A file over ``direct_upload_threshold`` sent in a request body."""

    status_code = 413
    code = constants.CODE_USE_DIRECT_UPLOAD


class InvalidUpload(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A 422 with a code: bad metadata, bad base64, too many files."""

    status_code = 422

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail, code)


class InvalidGroup(Invalid):
    """A 422 about a group, role or regroup pattern, with a code the console words."""

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail, code)


class GroupExists(Conflict):
    code = constants.CODE_GROUP_EXISTS


class UploadFailed(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A file of a batch failed for a reason that is not the client's."""

    status_code = 500
    code = constants.CODE_UPLOAD_FAILED


class StorageQuotaExceeded(ImagesError):  # noqa: N818 - billing's vocabulary
    """The plan's ``images.storage_bytes`` limit leaves no room (402, as
    billing's own refusals answer)."""

    status_code = 402
    code = constants.CODE_QUOTA_EXCEEDED


class TooManyOpenUploads(ImagesError):  # noqa: N818 - HTTP vocabulary, deliberately
    """The tenant already has ``max_open_uploads_per_tenant`` uploads open (429)."""

    status_code = 429
    code = constants.CODE_TOO_MANY_OPEN_UPLOADS


class UploadNotFound(NotFound):
    code = constants.CODE_UPLOAD_NOT_FOUND


class PartsMismatch(Conflict):
    code = constants.CODE_PARTS_MISMATCH


class UploadInProgress(Conflict):
    """The upload session is claimed by a ``complete`` that is still running."""

    code = constants.CODE_UPLOAD_IN_PROGRESS


class UploadNotOpen(Conflict):
    """A part sent after a complete claimed (or finished) the upload."""

    code = constants.CODE_UPLOAD_NOT_OPEN


class DirectUploadUnsupported(ServiceUnavailable):
    code = constants.CODE_DIRECT_UNSUPPORTED


class TenantRequired(Forbidden):
    """A multi-tenant host, and a signed-in request the framework resolved no
    tenant for (no active organisation). Refused rather than guessed; the same
    status and code as pagebuilder's, news' and records' admin refusal."""

    code = constants.TENANT_REQUIRED_CODE


def absent() -> HTTPException:
    """What the framework's ``RequiresResource`` raises for an id the caller
    cannot see. Withheld (redaction pending) and nonexistent must fail the same
    way in every negotiation (JSON, HTML, Inertia), so the withheld paths raise
    this rather than a module ``NotFound``."""
    return HTTPException(status_code=404, detail="Not found")


async def _error_page(request: Request, exc: ImagesError) -> Response | None:
    """The host's Inertia error page, for a console screen (records does the
    same). ``None`` when the host cannot render one, so the caller answers JSON
    rather than stacking an error on the refusal."""
    config = getattr(getattr(request.app.state, "sm", None), "inertia_config", None)
    if config is None:
        return None
    try:
        from simple_module_hosting._error_handlers import render_error_page

        return await render_error_page(request, exc.status_code, exc.detail)
    except Exception:  # pragma: no cover - a framework without the function
        return None


async def render(request: Request, exc: ImagesError) -> Response:
    path = request.url.path
    if path.startswith((f"{constants.VIEW_PREFIX}/", constants.PUBLIC_COLLECTION_PREFIX)):
        page = await _error_page(request, exc)
        if page is not None:
            return page
    body: dict[str, str] = {"detail": exc.detail}
    if exc.code is not None:
        body["code"] = exc.code
    return JSONResponse(body, status_code=exc.status_code)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ImagesError, render)  # type: ignore[arg-type]
