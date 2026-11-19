"""The registration mail: one plain-text message to the address that registered (PR 9).

The title, when and where of the event (in **the event's** zone and the registrant's language, as
events formats them), the event page and its ``.ics`` (**linked, not attached**: the framework's
``MailMessage`` at this version has ``to, subject, text, html`` and no attachments; upstream
simple_module_python #1006 asks for them), the confirm link while the registration is pending, the
cancel link, and why the address got it.

**Text only, one line per value.** There is no HTML part, so there is nothing to escape into: every
value that came from an event or a visitor is reduced to one line without control, direction or
separator characters before it is used anywhere, the subject doubly so and bounded.

**Links.** The confirm and cancel links are records' own (``public_base_url``, the tenant in the
token). The event's page and ``.ics`` are on the host's public base URL on a single-tenant host;
on a multi-tenant host a tenant's public origin is a property of the request, so they use the submit
request's ``Origin``, which the abuse guard has already accepted as this host's.

**After the commit, never the outbox**, like the newsletter's confirmation: the links need the
host's ``secret_key``, which only the web process has, held in the task's closure. A claim per
recipient (:func:`~sm_records.public_submissions.confirmation.recipient_key`) means a retry never
mails an address twice. The mail asks nothing of the log: no address, no name, no link.
"""

from __future__ import annotations

import logging
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final
from urllib.parse import urlsplit

from simple_module_core.mail import MailMessage, MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import TenancyMode, mode_of
from sm_records.models import Record, RecordType
from sm_records.public_submissions import links, strings
from sm_records.public_submissions.confirmation import recipient_key
from sm_records.public_submissions.delivery import SessionFactory, load
from sm_records.public_submissions.mail import template
from sm_records.public_submissions.mail_runner import queue, ui_locale
from sm_records.public_submissions.sending import send_all
from sm_records.public_submissions.tokens import host_secret, public_base_url
from sm_records.records.services._common import utcnow

__all__ = ["RegistrationDue", "event_base_url", "message", "queue_registration_mail"]

logger = logging.getLogger(__name__)

SUBJECT_MAX: Final = 200
_PENDING: Final = "pending"
_DROPPED: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})


@dataclass
class RegistrationDue:
    """In-process only (never published to the outbox): which registration to mail, and the event
    facts it was admitted with. Identifiers, base URLs and a locale: no address, no link."""

    tenant_id: str
    type_key: str
    uuid: str
    base_url: str
    locale: str
    attempt: str
    event_base: str
    event: Any


def _text(key: str, locale: str, **params: Any) -> str:
    return strings.text(f"mail.registration.{key}", locale, **params)


def _line(value: Any) -> str:
    """One line: whitespace collapsed, control, direction and separator characters gone."""
    kept = "".join(ch for ch in str(value or "") if unicodedata.category(ch) not in _DROPPED)
    return " ".join(kept.split())


def _multi_tenant(app: Any) -> bool:
    return mode_of(app) is TenancyMode.MULTI


def event_base_url(request: Any) -> str:
    """Where the event's page and ``.ics`` are: the submit request's accepted ``Origin`` on a
    multi-tenant host, else the host's ``public_base_url``."""
    if _multi_tenant(request.app):
        parts = urlsplit(request.headers.get("origin") or "")
        if parts.scheme in ("http", "https") and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return public_base_url(request.app)


def _ics_path(event: Any) -> str:
    """The ``.ics`` of the event, and of the occurrence when the page names one (``?date=``)."""
    query = urlsplit(event.page_path).query
    return event.ics_path + (f"?{query}" if query else "")


def message(
    rtype: RecordType,
    record: Record,
    event: Any,
    *,
    secret: str,
    base_url: str,
    event_base: str,
    locale: str,
    ttl_hours: int,
    now: float | None = None,
) -> MailMessage:
    """The mail for ``record`` with its links minted now."""
    data = record.data or {}
    pending = data.get("sm_status") == _PENDING
    hold = int((rtype.public_submissions or {}).get("pending_hold_hours") or ttl_hours)
    exp = int((time.time() if now is None else now) + min(ttl_hours, hold) * 3600)
    claims = {
        "tenant": rtype.tenant_id,
        "type_key": rtype.key,
        "uuid": record.uuid,
        "nonce": str(data.get("sm_nonce") or ""),
    }
    site = urlsplit(base_url).netloc or base_url
    title = _line(event.title)
    blocks = []
    if pending:
        confirm = links.sign(secret, links.CONFIRM, exp=exp, **claims)
        expires = datetime.fromtimestamp(exp, UTC).strftime("%Y-%m-%d %H:%M UTC")
        blocks.append(
            f"{_text('confirm', locale)}\n"
            f"{links.url(base_url, links.CONFIRM, confirm, locale)}\n\n"
            f"{_text('expiry', locale, expires=expires)}\n\n"
        )
    cancel = links.sign(secret, links.CANCEL, **claims)
    place = ", ".join(part for part in (_line(event.venue_name), _line(event.address)) if part)
    online = _line(event.online_url)
    body = template("registration.txt").substitute(
        intro=_text(
            "intro_pending" if pending else "intro_registered", locale, title=title, site=site
        ),
        title=title,
        when=f"{_text('when', locale)} {_line(event.when_text)}",
        place=f"\n{_text('place', locale)} {place}" if place else "",
        online=f"\n{_text('online', locale)} {online}" if online else "",
        page_label=_text("page", locale),
        page_link=f"{event_base}{event.page_path}",
        ics_label=_text("ics", locale),
        ics_link=f"{event_base}{_ics_path(event)}",
        confirm_block="".join(blocks),
        cancel_label=_text("cancel", locale),
        cancel_link=links.url(base_url, links.CANCEL, cancel, locale),
        why=_text("why", locale, site=site),
    )
    subject = _text(
        "subject_pending" if pending else "subject_registered", locale, title=title, site=site
    )
    return MailMessage(
        to=str(data.get("sm_email") or ""), subject=_line(subject)[:SUBJECT_MAX], text=body
    )


async def _send(
    secret: str,
    db: AsyncSession,
    sender: MailSender,
    due: RegistrationDue,
    settings: RecordsSettings,
    factory: SessionFactory,
) -> None:
    loaded = await load(db, due)
    if loaded is None:
        return
    rtype, record = loaded
    data = record.data or {}
    if data.get("sm_status") not in (_PENDING, "registered") or not data.get("sm_email"):
        logger.info("records: %s registration %s is not live; not mailed", rtype.key, record.uuid)
        return
    mail = message(
        rtype,
        record,
        due.event,
        secret=secret,
        base_url=due.base_url,
        event_base=due.event_base,
        locale=strings.catalogue_locale(data.get("sm_locale"), due.locale),
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
        [(recipient_key(secret, rtype.tenant_id, mail.to), mail)],
        lambda: {"sm_confirm_sent_at": utcnow()},
    )


async def queue_registration_mail(
    db: AsyncSession, request: Any, rtype: RecordType, record: Record, event: Any
) -> None:
    """Send ``record`` its registration mail once ``db`` commits."""
    app = request.app
    due = RegistrationDue(
        tenant_id=rtype.tenant_id,
        type_key=rtype.key,
        uuid=record.uuid,
        base_url=public_base_url(app),
        locale=ui_locale(app),
        attempt=uuid.uuid4().hex,
        event_base=event_base_url(request),
        event=event,
    )
    await queue(db, app, due, partial(_send, host_secret(app)), durable=False)
