"""The failures events reports deliberately, and their JSON mapping.

Services never import FastAPI, so they raise these and the app-level handler
installed by :func:`install_exception_handlers` renders them. The body is
``{"detail": ..., "code": ...}``, plus ``"field"`` when the refusal belongs to one
input; FastAPI's own request-validation 422 keeps its standard shape.
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
    headers: dict[str, str] | None = None
    """Extra response headers; the body is always exactly ``detail`` and ``code``."""
    field: str | None = None
    """The request input the refusal belongs to (a dotted path such as ``times.end`` or
    ``texts.de.slug``), when the server knows. It is the body's only extra key."""

    def __init__(
        self, detail: str | None = None, code: str | None = None, field: str | None = None
    ) -> None:
        if detail is not None:
            self.detail = detail
        if code is not None:  # else the class default stands
            self.code = code
        if field is not None:
            self.field = field
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


class Stale(Conflict):
    """The caller's ``expected_revision`` is not the event's. The current one rides
    in a header (and on the instance), never in the body."""

    code = constants.STALE_CODE
    detail = constants.STALE_DETAIL

    def __init__(self, current_revision: int | None = None) -> None:
        super().__init__()
        self.current_revision = current_revision
        if current_revision is not None:
            self.headers = {constants.CURRENT_REVISION_HEADER: str(current_revision)}


class OverridesOrphaned(Conflict):
    code = constants.OVERRIDES_ORPHANED_CODE
    detail = constants.OVERRIDES_ORPHANED_DETAIL


class HasSubEvents(Conflict):
    code = constants.HAS_SUB_EVENTS_CODE
    detail = constants.HAS_SUB_EVENTS_DETAIL


class InvalidTransition(Conflict):
    code = constants.INVALID_TRANSITION_CODE
    detail = constants.INVALID_TRANSITION_DETAIL


class PublishRequired(Forbidden):
    """A writer who may see the event but not change a locked one."""

    code = constants.PUBLISH_REQUIRED_CODE
    detail = constants.PUBLISH_REQUIRED_DETAIL


class InvalidRule(Invalid):
    """Also raised with ``rrule_frequency_refused`` and ``start_not_in_rule``."""

    code = constants.INVALID_RRULE_CODE
    detail = constants.INVALID_RRULE_DETAIL


class InvalidTimes(Invalid):
    """Also raised with ``end_before_start`` and ``duration_too_long``."""

    code = constants.INVALID_LOCAL_TIME_CODE
    detail = constants.INVALID_LOCAL_TIME_DETAIL


class InvalidRange(Invalid):
    """Also raised with ``range_too_long``."""

    code = constants.INVALID_RANGE_CODE
    detail = constants.INVALID_RANGE_DETAIL


class DefaultLocaleRequired(Invalid):
    code = constants.DEFAULT_LOCALE_REQUIRED_CODE
    detail = constants.DEFAULT_LOCALE_REQUIRED_DETAIL


class UnknownCategory(Invalid):
    code = constants.UNKNOWN_CATEGORY_CODE
    detail = constants.UNKNOWN_CATEGORY_DETAIL


class UnknownType(Invalid):
    code = constants.UNKNOWN_TYPE_CODE
    detail = constants.UNKNOWN_TYPE_DETAIL


class InvalidParent(Invalid):
    code = constants.INVALID_PARENT_CODE
    detail = constants.INVALID_PARENT_DETAIL


class ImmutableField(Invalid):
    code = constants.IMMUTABLE_FIELD_CODE
    detail = constants.IMMUTABLE_FIELD_DETAIL


class NotRecurring(Invalid):
    code = constants.NOT_RECURRING_CODE
    detail = constants.NOT_RECURRING_DETAIL


class NotAnOccurrence(Invalid):
    code = constants.NOT_AN_OCCURRENCE_CODE
    detail = constants.NOT_AN_OCCURRENCE_DETAIL


class DescriptionTooLong(Invalid):
    code = constants.DESCRIPTION_TOO_LONG_CODE
    detail = constants.DESCRIPTION_TOO_LONG_DETAIL


class SlugReserved(Invalid):
    """An explicit slug that a public route segment already owns."""

    code = constants.SLUG_RESERVED_CODE
    detail = constants.SLUG_RESERVED_DETAIL


class ServiceUnavailable(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 503
    code = "service_unavailable"
    detail = "Service unavailable"


class TokenLimit(Conflict):
    """The user already holds the most private links one calendar allows."""

    code = constants.TOKEN_LIMIT_CODE
    detail = constants.TOKEN_LIMIT_DETAIL


class ImportBusy(Conflict):
    code = constants.IMPORT_BUSY_CODE
    detail = constants.IMPORT_BUSY_DETAIL


class ImportState(Conflict):
    code = constants.IMPORT_STATE_CODE
    detail = constants.IMPORT_STATE_DETAIL


class ImportTooLarge(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 413
    code = constants.IMPORT_TOO_LARGE_CODE
    detail = constants.IMPORT_TOO_LARGE_DETAIL


class IcsInvalid(Invalid):
    code = constants.ICS_INVALID_CODE
    detail = constants.ICS_INVALID_DETAIL


class PrivateFeedsUnavailable(ServiceUnavailable):
    """The caller's rights cannot be worked out without their session (the identity provider
    keeps their roles), so a link could never serve anything: none is handed out."""

    code = constants.PRIVATE_FEEDS_UNAVAILABLE_CODE
    detail = constants.PRIVATE_FEEDS_UNAVAILABLE_DETAIL


class ImportFailure(Exception):  # noqa: N818 - not an HTTP error
    """An import step that cannot go on. Carries a failure ``code`` and nothing else: a
    library's message can echo the file, so it is never kept."""

    def __init__(self, code: str, bound: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.bound = bound
        """Which limit tripped (``"line_length"``), never a value from the file."""


def install_exception_handlers(app: FastAPI) -> None:
    """Render every :class:`EventsError` as ``{"detail", "code"}``."""

    @app.exception_handler(EventsError)
    async def _events_error(_request: Request, exc: EventsError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "code": exc.code,
                **({"field": exc.field} if exc.field else {}),
            },
            headers=exc.headers,
        )
