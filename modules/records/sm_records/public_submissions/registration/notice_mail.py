"""The mail to an address that registered nothing: why a submit found the event full or closed.

Split from :mod:`.mail` (the confirmation and "already registered" mail of a record). In-process
only and never stored: there is no record, so nothing about the address is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from simple_module_core.mail import MailMessage, MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordType
from sm_records.public_submissions import strings
from sm_records.public_submissions.mail_runner import queue
from sm_records.public_submissions.registration.mail import SUBJECT_MAX, _line, _text
from sm_records.public_submissions.tokens import public_base_url

__all__ = ["NoticeDue", "notice_message", "queue_notice_mail"]


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
