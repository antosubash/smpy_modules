"""What a send needs from the settings and the campaign: the sender
configuration and the header inputs (ruling C6), shared by the test send and
scheduling, and the checks only scheduling makes (ruling S19, A6, A7)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sm_newsletter.content.merge import check_no_capability
from sm_newsletter.content.render import RenderContext
from sm_newsletter.core.errors import HttpsRequired, InvalidCampaign, SenderNotConfigured
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign


def check_sender(settings: NewsletterSettings) -> None:
    required = ["from_address", "physical_address"]
    if settings.transport == "smtp":
        required.append("smtp_host")
    for field in required:
        if not (getattr(settings, field) or "").strip():
            raise SenderNotConfigured(f"{field} is not set")
    for field in ("from_name", "from_address", "reply_to"):
        try:
            check_header_text(getattr(settings, field) or "", field=field)
        except ValueError as exc:
            raise SenderNotConfigured(str(exc)) from None


def check_campaign_headers(campaign: Campaign) -> None:
    for field in ("subject", "from_name", "reply_to"):
        value = getattr(campaign, field)
        if value is None:
            continue
        try:
            check_header_text(value, field=field)
        except ValueError as exc:
            raise InvalidCampaign(str(exc)) from None


SCHEDULE_GRACE = timedelta(seconds=60)
SCHEDULE_HORIZON = timedelta(days=366)


def check_scheduled_at(scheduled_at: datetime | None, now: datetime) -> datetime:
    """When to send: ``now`` for ``None``, else an aware time within
    ``[now - 60 s, now + 366 days]``."""
    if scheduled_at is None:
        return now
    aware = scheduled_at.tzinfo is not None and scheduled_at.utcoffset() is not None
    if not aware or not now - SCHEDULE_GRACE <= scheduled_at <= now + SCHEDULE_HORIZON:
        raise InvalidCampaign("scheduled_at: out of range")
    return scheduled_at


def bases_https(*bases: str) -> bool:
    """Whether every base is ``https://`` (an empty one is not)."""
    return all(base.lower().startswith("https://") for base in bases)


def check_https(settings: NewsletterSettings, ctx: RenderContext) -> None:
    """Amendment A6: real mail carries capability links, so both bases are
    ``https://`` on the SMTP transport. The console transport allows ``http://``.
    The transport can change after scheduling, so the dispatcher checks the
    stored snapshot again before SMTP delivery (``sending.upkeep.pause_insecure``)."""
    if settings.transport == "smtp" and not bases_https(ctx.content_base, ctx.public_base):
        raise HttpsRequired()


def check_no_capability_fields(campaign: Campaign) -> None:
    """Amendment A7, again at schedule for rows written around the API."""
    for field in ("subject", "preheader"):
        try:
            check_no_capability(getattr(campaign, field), field=field)
        except ValueError as exc:
            raise InvalidCampaign(str(exc)) from None
