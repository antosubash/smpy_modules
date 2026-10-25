"""The newsletter's confirmation mail (#101, design §6 and §7.1).

One message to the address that signed up: the confirm link and when it
expires, the unsubscribe link, and why the address got it — plain text from
``templates/confirm.txt``, in the subscriber's ``sm_locale`` when this
module's catalogue has it, else the host's default language.

**After the commit, never the outbox.** The links are minted when the message
is built, from the record's current ``sm_nonce``, so nothing secret is ever
stored. That needs the host's ``secret_key``, which only the web process has:
the outbox worker builds the module with no app. So the confirmation always
takes the after-commit path of :mod:`.mail_runner`, with the secret held in
the task's closure and nowhere else. A crash can lose it; ``sm_confirm_sent_at``
then stays empty, and either the visitor signing up again or an admin's
*Resend* sends it.

It goes through the same per-recipient claims as the notification
(:mod:`.delivery`), so a retry of one attempt never mails the address twice,
and only to a subscriber who is still ``pending`` when it is built.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final
from urllib.parse import urlsplit

from fastapi import Request
from simple_module_core.mail import MailMessage, MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType
from sm_records.public_submissions import abuse, links, strings
from sm_records.public_submissions.delivery import SessionFactory, load, send_all
from sm_records.public_submissions.mail import template
from sm_records.public_submissions.mail_runner import queue, ui_locale
from sm_records.public_submissions.tokens import host_secret, public_base_url
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings

__all__ = ["PENDING", "ConfirmationDue", "message", "queue_confirmation", "within_budget"]

logger = logging.getLogger(__name__)

PENDING: Final = "pending"


@dataclass
class ConfirmationDue:
    """In-process only (never published to the outbox): which subscriber to
    mail. Identifiers, the base URL and a fallback language — no address and
    no link."""

    tenant_id: str
    type_key: str
    uuid: str
    base_url: str
    locale: str
    attempt: str


def _text(key: str, locale: str, **params: Any) -> str:
    return strings.text(f"mail.confirm.{key}", locale, **params)


def message(
    rtype: RecordType,
    record: Record,
    *,
    secret: str,
    base_url: str,
    locale: str,
    ttl_hours: int,
    now: float | None = None,
) -> MailMessage:
    """The confirmation for ``record``, with both links minted now."""
    data = record.data or {}
    exp = int((time.time() if now is None else now) + ttl_hours * 3600)
    claims = {
        "tenant": rtype.tenant_id,
        "type_key": rtype.key,
        "uuid": record.uuid,
        "nonce": str(data.get("sm_nonce") or ""),
    }
    confirm = links.sign(secret, links.CONFIRM, exp=exp, **claims)
    unsubscribe = links.sign(secret, links.UNSUBSCRIBE, **claims)
    site = urlsplit(base_url).netloc or base_url
    expires = datetime.fromtimestamp(exp, UTC).strftime("%Y-%m-%d %H:%M UTC")
    body = template("confirm.txt").substitute(
        intro=_text("intro", locale, list=rtype.label, site=site),
        confirm_label=_text("confirm", locale),
        confirm_link=links.url(base_url, links.CONFIRM, confirm, locale),
        expiry=_text("expiry", locale, expires=expires),
        why=_text("why", locale, site=site),
        unsubscribe_label=_text("unsubscribe", locale),
        unsubscribe_link=links.url(base_url, links.UNSUBSCRIBE, unsubscribe, locale),
    )
    subject = _text("subject", locale, list=rtype.label, site=site)
    return MailMessage(to=str(data.get("sm_email") or ""), subject=subject, text=body)


async def _send(
    secret: str,
    db: AsyncSession,
    sender: MailSender,
    due: ConfirmationDue,
    settings: RecordsSettings,
    factory: SessionFactory,
) -> None:
    loaded = await load(db, due)
    if loaded is None:
        return
    rtype, record = loaded
    data = record.data or {}
    if data.get("sm_status") != PENDING or not data.get("sm_email"):
        logger.info("records: %s subscriber %s is not pending; not mailed", rtype.key, record.uuid)
        return
    locale = strings.catalogue_locale(data.get("sm_locale"), due.locale)
    mail = message(
        rtype,
        record,
        secret=secret,
        base_url=due.base_url,
        locale=locale,
        ttl_hours=settings.public_submissions_confirm_ttl_hours,
    )
    await send_all(
        db,
        rtype,
        record,
        sender,
        due,
        settings,
        factory,
        [(mail.to, mail)],
        lambda: {"sm_confirm_sent_at": utcnow()},
    )


async def within_budget(
    request: Request, rtype: RecordType, email: str, settings: RecordsSettings
) -> bool:
    """Count one confirmation against the address's budget on this list.
    Keyed by a hash, so the address itself is never a rate-limit key."""
    digest = hashlib.sha256(email.encode()).hexdigest()
    key = abuse.rate_key(rtype.tenant_id, f"{rtype.key}:email={digest}")
    return await abuse.allow(request, key, settings.public_submissions_confirm_rate_per_email)


async def queue_confirmation(db: AsyncSession, app: Any, rtype: RecordType, record: Record) -> None:
    """Send ``record`` its confirmation once ``db`` commits."""
    due = ConfirmationDue(
        tenant_id=rtype.tenant_id,
        type_key=rtype.key,
        uuid=record.uuid,
        base_url=public_base_url(app),
        locale=ui_locale(app),
        attempt=uuid.uuid4().hex,
    )
    await queue(db, app, due, partial(_send, host_secret(app)), durable=False)
