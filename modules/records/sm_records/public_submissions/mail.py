"""The notification a contact-form submission sends its recipients (#101).

Plain text, from ``templates/notify.txt`` (``string.Template``) with the strings
from this module's own catalogue (``locales/<locale>.json``,
``public_submissions.mail.notify.*``) in the host's default language: it goes
to staff, not to the visitor. Every public field is listed as ``label:
value`` with the type's own labels, and the message links to the record in
the console. There is no ``Reply-To``: the framework's ``MailMessage`` cannot
carry one, and copying the visitor's address into a header would be the
first thing a mail-bombing script tries.

The visitor's values leave the database here and only here, by design.
"""

from __future__ import annotations

import importlib.resources
from functools import cache
from string import Template
from typing import Any, Final
from urllib.parse import urlsplit

from simple_module_core.mail import MailMessage, MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.models import Record, RecordType
from sm_records.public_submissions import strings
from sm_records.public_submissions.delivery import SessionFactory
from sm_records.public_submissions.sending import send_all
from sm_records.services._common import utcnow
from sm_records.services._payload import field_defs
from sm_records.settings import RecordsSettings

__all__ = ["deliver", "notification", "template", "text"]

_EMPTY: Final = "—"


def text(key: str, locale: str | None, **params: Any) -> str:
    """``public_submissions.mail.notify.<key>`` in ``locale``, else English."""
    return strings.text(f"mail.notify.{key}", locale, **params)


@cache
def template(name: str) -> Template:
    path = importlib.resources.files(__package__) / "templates" / name
    return Template(path.read_text(encoding="utf-8"))


def _value(value: Any) -> str:
    if value is None or value == "" or value == []:
        return _EMPTY
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, bool):
        return "✓" if value else "✗"
    return str(value)


def _lines(rtype: RecordType, record: Record) -> str:
    config = rtype.public_submissions or {}
    labels = {entry.key: entry.label for entry in field_defs(rtype)}
    data = record.data or {}
    return "\n".join(
        f"{labels.get(key, key)}: {_value(data.get(key))}"
        for key in config.get("public_fields", [])
    )


def notification(
    rtype: RecordType, record: Record, *, to: str, base_url: str, locale: str | None
) -> MailMessage:
    site = urlsplit(base_url).netloc or base_url
    link = f"{base_url}{constants.VIEW_PREFIX}/{rtype.key}/{record.uuid}"
    body = template("notify.txt").substitute(
        intro=text("intro", locale, type=rtype.label, site=site),
        fields=_lines(rtype, record),
        open_label=text("open", locale),
        link=link,
        footer=text("footer", locale, site=site),
    )
    return MailMessage(
        to=to, subject=text("subject", locale, type=rtype.label, site=site), text=body
    )


async def deliver(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    sender: MailSender,
    due: Any,
    settings: RecordsSettings,
    factory: SessionFactory,
) -> None:
    """A submission's notification: every ``notify_to`` address, then
    ``sm_notified_at``."""

    # Built before the claims: a failure here must not leave a claim that
    # blocks the retry for a whole lease.
    def build(to: str) -> MailMessage:
        return notification(rtype, record, to=to, base_url=due.base_url, locale=due.locale)

    messages = [(to, build(to)) for to in (rtype.public_submissions or {}).get("notify_to", [])]
    await send_all(
        db,
        rtype,
        record,
        sender,
        due,
        settings,
        factory,
        messages,
        lambda: {"sm_notified_at": utcnow()},
        build,
    )
