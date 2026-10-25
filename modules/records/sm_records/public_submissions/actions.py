"""What an admin can do to a website submission beyond an ordinary edit (#101).

**The trash is the spam folder.** *Mark as spam* writes ``sm_spam="manual"``
and trashes the record; *Not spam* restores it, clears the mark and sends the
notification a spam submission never got. Telling spam from an ordinary
deletion is what ``sm_spam`` is for — both live in one view. *Resend* queues
the notification again, for a record whose mail was lost ("not sent") or
needs to reach somebody again; it is throttled per record.

Each refuses a type that is not a contact form with ``409 wrong_kind``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_FORM
from sm_records.models import Record, RecordType
from sm_records.public_submissions import abuse
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.mail_runner import queue_notification
from sm_records.public_submissions.system import system_update
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = ["RESEND_RATE", "mark_not_spam", "mark_spam", "require_form", "resend"]

RESEND_RATE = "1/minute"
"""One resend per record per minute: enough to recover, too little to spam
the recipients with."""


def require_form(rtype: RecordType) -> None:
    if (rtype.public_submissions or {}).get("kind") != KIND_FORM:
        raise SubmissionRefused(
            "wrong_kind", f"type {rtype.key!r} does not take contact-form submissions"
        )


async def resend(
    db: AsyncSession, app: Any, request: Any, rtype: RecordType, record: Record
) -> None:
    require_form(rtype)
    if not (rtype.public_submissions or {}).get("notify_to"):
        raise SubmissionRefused("no_recipients", f"type {rtype.key!r} notifies nobody")
    await abuse.hit(request, abuse.rate_key(bound_tenant(), f"resend={record.uuid}"), RESEND_RATE)
    await queue_notification(db, app, rtype, record)


async def mark_spam(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    settings: RecordsSettings,
    actor: str | None,
    roles: list[str],
) -> Record:
    require_form(rtype)
    record = await system_update(db, rtype, record, {"sm_spam": "manual"}, settings=settings)
    await record_service.soft_delete_record(
        db, rtype, record, actor=actor, settings=settings, roles=roles
    )
    return record


async def mark_not_spam(
    db: AsyncSession,
    app: Any,
    rtype: RecordType,
    record: Record,
    *,
    settings: RecordsSettings,
    actor: str | None,
) -> Record:
    require_form(rtype)
    if not record.is_deleted:
        raise SubmissionRefused("not_in_trash", "only a submission in the trash can be not spam")
    record = await record_service.restore_record(db, rtype, record, settings=settings, actor=actor)
    record = await system_update(db, rtype, record, {"sm_spam": None}, settings=settings)
    await queue_notification(db, app, rtype, record)
    return record
