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


class InvalidSettings(NewsletterError):  # noqa: N818 - names the payload
    """A settings payload that fails its schema. Names the field, never the value."""

    status = 422
    code = "invalid_settings"
    detail = "The settings are not valid"


class OutboxUnavailable(NotFound):
    """The capture outbox exists only on the console transport."""


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


class InvalidTransition(NewsletterError):  # noqa: N818 - the state it refuses
    """The action does not apply to the campaign's current status (ruling S14)."""

    status = 409
    code = "invalid_transition"
    detail = "This action does not apply to the campaign in its current state"


class EmptyCampaign(NewsletterError):  # noqa: N818 - the state it refuses
    """A campaign with no blocks cannot be sent."""

    status = 422
    code = "empty_campaign"
    detail = "Add content to the campaign before sending it"


class HttpsRequired(NewsletterError):  # noqa: N818 - names the setting
    """On the SMTP transport, the email's links and the unsubscribe page must be
    ``https://`` (amendment A6): the unsubscribe link carries a capability."""

    status = 422
    code = "https_required"
    detail = "The site's public address must use https before sending"


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
    names the stage (``connect``, ``tls``, ``auth``), as does ``stage``, and
    never holds the username, the password or the server's AUTH reply."""

    stage: str | None

    status = 502
    code = "transport_unavailable"
    detail = "The mail server is not available"

    def __init__(self, detail: str | None = None, *, stage: str | None = None) -> None:
        super().__init__(detail)
        self.stage = stage


class CampaignCancelled(NewsletterError):  # noqa: N818 - the state it refuses
    status = 409
    code = "campaign_cancelled"
    detail = "A cancelled campaign cannot be test sent"


class SenderNotConfigured(NewsletterError):  # noqa: N818 - names the setting
    """A newsletter setting a send needs is blank or unusable; the detail names it."""

    status = 422
    code = "sender_not_configured"
    detail = "The sender is not configured"


class PublicBaseUrlRequired(NewsletterError):  # noqa: N818 - names the setting
    """The host has no ``public_base_url``, so the email's links would be relative."""

    status = 422
    code = "public_base_url_required"
    detail = "Set the site's public address (public_base_url) before sending"


class SendBudgetExhausted(NewsletterError):  # noqa: N818 - the state it refuses
    """The rolling daily or per-minute sending limit has no room for this send."""

    status = 429
    code = "send_budget_exhausted"
    detail = "The sending limit is reached; try again later"


class DispatchBusy(NewsletterError):  # noqa: N818 - the state it refuses
    """Another send held the install-wide dispatch lock for the whole wait."""

    status = 409
    code = "dispatch_busy"
    detail = "Another send is in progress; try again shortly"


async def render(request: Request, exc: NewsletterError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NewsletterError, render)  # type: ignore[arg-type]
