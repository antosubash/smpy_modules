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
token). The event's page and ``.ics`` come from :mod:`.origin`: configuration only, never a request
header, and absent (not guessed) when no trusted origin is known.

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

from sm_records.contracts.public_submissions import DEFAULT_PENDING_HOLD_HOURS
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType
from sm_records.public_submissions import links, strings
from sm_records.public_submissions.confirmation import recipient_key
from sm_records.public_submissions.delivery import SessionFactory, load
from sm_records.public_submissions.mail import template
from sm_records.public_submissions.mail_runner import queue, ui_locale
from sm_records.public_submissions.registration.origin import event_base
from sm_records.public_submissions.registration.status import LIVE, PENDING
from sm_records.public_submissions.sending import send_all
from sm_records.public_submissions.tokens import host_secret, public_base_url
from sm_records.records.services._common import utcnow

__all__ = [
    "NoticeDue",
    "RegistrationDue",
    "message",
    "queue_notice_mail",
    "queue_registration_mail",
]

logger = logging.getLogger(__name__)
_CONFIRM_PAGE = links.CONFIRM_REGISTRATION_PAGE

SUBJECT_MAX: Final = 200
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
    event: Any
    kind: str = "registration"
    """``"already"``: submitted again while registered: told so, with the cancel link."""


def _text(key: str, locale: str, **params: Any) -> str:
    return strings.text(f"mail.registration.{key}", locale, **params)


def _line(value: Any) -> str:
    """One line: whitespace collapsed, control, direction and separator characters gone."""
    kept = "".join(ch for ch in str(value or "") if unicodedata.category(ch) not in _DROPPED)
    return " ".join(kept.split())


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
    kind: str = "registration",
) -> MailMessage:
    """The mail for ``record`` with its links minted now."""
    data = record.data or {}
    pending = data.get("sm_status") == PENDING
    hold = int(
        (rtype.public_submissions or {}).get("pending_hold_hours") or DEFAULT_PENDING_HOLD_HOURS
    )
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
            f"{links.url(base_url, links.CONFIRM, confirm, locale, page=_CONFIRM_PAGE)}\n\n"
            f"{_text('expiry', locale, expires=expires)}\n\n"
        )
    cancel = links.sign(secret, links.CANCEL, **claims)
    place = ", ".join(part for part in (_line(event.venue_name), _line(event.address)) if part)
    online = _line(event.online_url)
    body = template("registration.txt").substitute(
        intro=_text(
            "intro_already"
            if kind == "already"
            else ("intro_pending" if pending else "intro_registered"),
            locale,
            title=title,
            site=site,
        ),
        title=title,
        when=f"{_text('when', locale)} {_line(event.when_text)}",
        place=f"\n{_text('place', locale)} {place}" if place else "",
        online=f"\n{_text('online', locale)} {online}" if online else "",
        page_block=(
            f"{_text('page', locale)}\n{event_base}{event.page_path}\n\n" if event_base else ""
        ),
        ics_block=(
            f"{_text('ics', locale)}\n{event_base}{_ics_path(event)}\n\n" if event_base else ""
        ),
        confirm_block="".join(blocks),
        cancel_label=_text("cancel", locale),
        cancel_link=links.url(base_url, links.CANCEL, cancel, locale),
        why=_text("why", locale, site=site),
    )
    subject = _text(
        "subject_already"
        if kind == "already"
        else ("subject_pending" if pending else "subject_registered"),
        locale,
        title=title,
        site=site,
    )
    return MailMessage(
        to=str(data.get("sm_email") or ""), subject=_line(subject)[:SUBJECT_MAX], text=body
    )


async def _send(
    secret: str,
    app: Any,
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
    if data.get("sm_status") not in LIVE or not data.get("sm_email"):
        logger.info("records: %s registration %s is not live; not mailed", rtype.key, record.uuid)
        return
    mail = message(
        rtype,
        record,
        due.event,
        secret=secret,
        base_url=due.base_url,
        event_base=await event_base(app, rtype.tenant_id, db),
        locale=strings.catalogue_locale(data.get("sm_locale"), due.locale),
        ttl_hours=settings.public_submissions_confirm_ttl_hours,
        kind=getattr(due, "kind", "registration"),
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
    db: AsyncSession,
    request: Any,
    rtype: RecordType,
    record: Record,
    event: Any,
    kind: str = "registration",
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
        event=event,
        kind=kind,
    )
    await queue(db, app, due, partial(_send, host_secret(app), app), durable=False)


@dataclass
class NoticeDue:
    """In-process only: a mail to an address that registered **nothing** (a full, closed or busy
    occurrence), so there is no record. It carries the address for the one send and is never logged
    or published."""

    tenant_id: str
    to: str
    locale: str
    base_url: str
    event: Any
    reason: str
    type_key: str = "-"
    uuid: str = "-"
    attempt: str = ""


def notice_message(due: NoticeDue, locale: str) -> MailMessage:
    site = urlsplit(due.base_url).netloc or due.base_url
    title = _line(due.event.title)
    body = (
        f"{_text(f'notice_{due.reason}', locale, title=title, site=site)}\n\n"
        f"{_text('notice_why', locale, site=site)}\n"
    )
    subject = _line(_text("notice_subject", locale, title=title, site=site))[:SUBJECT_MAX]
    return MailMessage(to=due.to, subject=subject, text=body)


async def _send_notice(
    db: AsyncSession, sender: MailSender, due: NoticeDue, settings: RecordsSettings, factory: Any
) -> None:
    await sender.send(notice_message(due, strings.catalogue_locale(due.locale)))


async def queue_notice_mail(
    db: AsyncSession,
    request: Any,
    rtype: RecordType,
    address: str,
    event: Any,
    reason: str,
    locale: str,
) -> None:
    """Tell ``address`` (stored nowhere) why its registration was not saved, once ``db`` commits.
    ``reason`` is ``full``, ``closed`` or ``busy``."""
    app = request.app
    due = NoticeDue(
        tenant_id=rtype.tenant_id,
        to=address,
        locale=locale,
        base_url=public_base_url(app),
        event=event,
        reason=reason,
    )
    await queue(db, app, due, _send_notice, durable=False)
