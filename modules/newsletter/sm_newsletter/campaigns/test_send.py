"""Send a campaign to up to five addresses, as the subscriber would see it.

Everything after the lookup runs inside the install-wide dispatch lock
(:mod:`sm_newsletter.sending.lock`, amendment 1): the sender configuration and
every header input are re-checked (amendment 5), the email is rendered, the
budget admits all the recipients or none (ruling C2: a refusal is 429 with
nothing sent and no ledger row), the transport session opens (a relay that
cannot be reached is 502, before any row), and then per recipient one ledger
row is committed ``pending`` before its SMTP call and closed with the result
after it.

The message is the campaign's own, with ``[TEST] `` before the subject, no
recipient name and the test unsubscribe link (R1), whose token the unsubscribe
page treats as forged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from email.utils import formataddr
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles, require_campaign
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context, test_unsubscribe_url
from sm_newsletter.content.render import WARN_RELATIVE, RenderInput, personalise, render
from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import (
    CampaignCancelled,
    InvalidCampaign,
    PublicBaseUrlRequired,
    SenderNotConfigured,
)
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign
from sm_newsletter.sending import ledger
from sm_newsletter.sending.budget import admit
from sm_newsletter.sending.lock import dispatch_lock
from sm_newsletter.sending.transport import OutgoingMessage, transport_for, unsubscribe_headers

__test__ = False  # a module named test_*, not a pytest test module

__all__ = ["MAX_TEST_RECIPIENTS", "TEST_SUBJECT_PREFIX", "TestSendResult", "send_test"]

MAX_TEST_RECIPIENTS = 5
TEST_SUBJECT_PREFIX = "[TEST] "
KIND = "test"
HOLDER = "test-send"


@dataclass(frozen=True)
class TestSendResult:
    recipient: str
    outcome: str
    code: int | None
    detail: str


async def send_test(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    recipients: list[str],
    roles: Roles,
    now: datetime | None = None,
) -> list[TestSendResult]:
    """Send campaign ``campaign_id`` to ``recipients`` (already normalised, 1 to 5).

    ``now`` pins the ledger's clock (tests); the rows of one call share it.
    """
    if not 1 <= len(recipients) <= MAX_TEST_RECIPIENTS:
        raise InvalidCampaign("recipients: invalid length")
    settings: NewsletterSettings = getattr(app.state, constants.PACKAGE).settings
    factory = app.state.sm.db.session_factory
    async with dispatch_lock(factory, holder=HOLDER):
        campaign = await require_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
        )
        if campaign.status == "cancelled":
            raise CampaignCancelled()
        _check_sender(settings)
        _check_headers(campaign)
        message = await _message(app, tenant_id, campaign, settings)
        transport = transport_for(settings)
        at = now or utcnow()
        await admit(factory, settings, n=len(recipients), now=at)
        results: list[TestSendResult] = []
        async with transport.session() as smtp:
            headers = dict(message.headers) if transport.supports_list_unsubscribe else {}
            for recipient in recipients:
                attempt = await ledger.open_attempt(
                    session,
                    tenant_id=tenant_id,
                    campaign_id=campaign.id,
                    send_id=None,
                    kind=KIND,
                    recipient=recipient,
                    now=at,
                )
                await finalize_session(session)
                outgoing = replace(message, to=recipient, headers=headers)
                result = await smtp.send(outgoing)
                await ledger.close_attempt(session, attempt, result)
                await finalize_session(session)
                results.append(
                    TestSendResult(recipient, result.outcome, result.code, result.detail)
                )
    return results


def _check_sender(settings: NewsletterSettings) -> None:
    required = ["from_address", "physical_address"]
    if settings.transport == "smtp":
        required.append("smtp_host")
    for field in required:
        if not str(getattr(settings, field)).strip():
            raise SenderNotConfigured(f"{field} is not set")
    for field in ("from_name", "from_address", "reply_to"):
        try:
            check_header_text(getattr(settings, field), field=field)
        except ValueError as exc:
            raise SenderNotConfigured(str(exc)) from None


def _check_headers(campaign: Campaign) -> None:
    for field in ("subject", "from_name", "reply_to"):
        value = getattr(campaign, field)
        if value is None:
            continue
        try:
            check_header_text(value, field=field)
        except ValueError as exc:
            raise InvalidCampaign(str(exc)) from None


async def _message(
    app: Any, tenant_id: str, campaign: Campaign, settings: NewsletterSettings
) -> OutgoingMessage:
    """The campaign's test message, addressed to nobody yet."""
    ctx = await render_context(app, tenant_id=tenant_id)
    blocks = parse_body(campaign.body)
    template = render(RenderInput(campaign.subject, campaign.preheader, blocks), ctx)
    if WARN_RELATIVE in template.warnings:
        raise PublicBaseUrlRequired()
    unsubscribe = test_unsubscribe_url(ctx.public_base)
    email = personalise(template, first_name=None, unsubscribe_url=unsubscribe)
    name = campaign.from_name or settings.from_name
    return OutgoingMessage(
        sender=formataddr((name, settings.from_address.strip())),
        to="",
        subject=check_header_text(TEST_SUBJECT_PREFIX + email.subject, field="subject"),
        html=email.html,
        text=email.text,
        reply_to=campaign.reply_to or settings.reply_to or None,
        headers=unsubscribe_headers(unsubscribe),
    )
