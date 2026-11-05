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


class SmtpPasswordUnreadable(NewsletterError):  # noqa: N818 - the brief's name for it
    """The stored SMTP password cannot be decrypted (the key changed)."""

    status = 500
    code = "smtp_password_unreadable"
    detail = "The stored SMTP password cannot be read; enter it again"


class InvalidPassword(NewsletterError):  # noqa: N818 - names the field
    """A blank or oversized SMTP password; the detail never repeats the value."""

    status = 422
    code = "invalid_password"
    detail = "The password must be 1 to 1024 characters and not blank"


class InvalidBody(NewsletterError):  # noqa: N818 - names the field
    """A campaign body that is not a valid list of email blocks. The detail
    names the path (``body[3].props.href: ...``) and never repeats the input."""

    status = 422
    code = "invalid_body"
    detail = "The body is not valid"


class InvalidCampaign(NewsletterError):  # noqa: N818 - names the payload
    """A campaign payload that fails its schema. The detail names the field and
    the error type, never the submitted value (it may be a header injection)."""

    status = 422
    code = "invalid_campaign"
    detail = "The campaign is not valid"


class NotADraft(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "not_a_draft"
    detail = "Only a draft campaign can be changed or deleted"


class StaleCampaign(NewsletterError):  # noqa: N818 - the state it refuses
    """The campaign moved on since the editor read it (``expected_revision``)."""

    status = 409
    code = "stale"
    detail = "The campaign was changed elsewhere; reload it"


class UnknownList(NewsletterError):  # noqa: N818 - names the field
    status = 422
    code = "unknown_list"
    detail = "No such newsletter list"


class ListForbidden(Forbidden):
    """The list exists, but records' ``allowed_roles`` shut this caller out."""

    code = "list_forbidden"
    detail = "You may not use this newsletter list"


class AudienceUnsupported(NewsletterError):  # noqa: N818 - names the field
    """Only ``all`` until segments (PR 6) and tags (PR 4) exist."""

    status = 422
    code = "audience_unsupported"
    detail = "Only the whole list can be the audience for now"


class IntegrationUnavailable(NewsletterError):  # noqa: N818 - the state it refuses
    """The content source a card or the media picker reads (news, pagebuilder)
    is not installed or not mounted on this host."""

    status = 409
    code = "integration_unavailable"
    detail = "This content source is not available on this site"


class CardSourceGone(NewsletterError):  # noqa: N818 - the state it refuses
    """A card's article or page is no longer published (unpublished, trashed or
    deleted); the stored snapshot is kept."""

    status = 409
    code = "card_source_gone"
    detail = "The card's source is no longer published; its snapshot was kept"


class BlockNotFound(NewsletterError):  # noqa: N818 - HTTP vocabulary, deliberately
    """No card block with that id in the campaign's body."""

    status = 404
    code = "block_not_found"
    detail = "No such card in this campaign"


class TransportUnavailable(NewsletterError):  # noqa: N818 - the state it reports
    """The mail relay could not be reached, secured or logged in to. The detail
    names the stage (``connect``, ``tls``, ``auth``) and never holds the
    username, the password or the server's AUTH reply."""

    status = 502
    code = "transport_unavailable"
    detail = "The mail server is not available"


async def render(request: Request, exc: NewsletterError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NewsletterError, render)  # type: ignore[arg-type]
