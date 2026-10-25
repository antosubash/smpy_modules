"""What an admin can do to a website submission beyond an ordinary edit (#101).

On a newsletter list: *Resend* sends a ``pending`` subscriber the
confirmation again (``409 not_pending`` otherwise; ``429`` past the address's
budget), and *Unsubscribe* does what the subscriber's own link does.

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

from sm_records.contracts.public_submissions import KIND_FORM, KIND_SUBSCRIPTION
from sm_records.deps import get_settings
from sm_records.models import Record, RecordType
from sm_records.public_submissions import abuse, opt_in
from sm_records.public_submissions.confirmation import PENDING, budget_wait, queue_confirmation
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.mail_runner import queue_notification
from sm_records.public_submissions.system import try_system_update
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = [
    "RESEND_RATE",
    "mark_not_spam",
    "mark_spam",
    "require_form",
    "require_subscription",
    "resend",
    "unsubscribe",
]

RESEND_RATE = "1/minute"
"""One resend per record per minute: enough to recover, too little to spam
the recipients with."""


def require_form(rtype: RecordType) -> None:
    if (rtype.public_submissions or {}).get("kind") != KIND_FORM:
        raise SubmissionRefused(
            "wrong_kind", f"type {rtype.key!r} does not take contact-form submissions"
        )


def require_subscription(rtype: RecordType) -> None:
    if (rtype.public_submissions or {}).get("kind") != KIND_SUBSCRIPTION:
        raise SubmissionRefused("wrong_kind", f"type {rtype.key!r} is not a newsletter list")


async def resend(
    db: AsyncSession, app: Any, request: Any, rtype: RecordType, record: Record
) -> None:
    """The notification again — or, on a newsletter list, the confirmation of
    a subscriber still ``pending``, against the address's own budget."""
    if (rtype.public_submissions or {}).get("kind") == KIND_SUBSCRIPTION:
        await _resend_confirmation(db, app, request, rtype, record)
        return
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
    record = await try_system_update(db, rtype, record, {"sm_spam": "manual"}, settings=settings)
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
    # Only a record kept *as spam*: restoring one a person deleted would mail
    # its recipients about a submission somebody already dealt with.
    if not record.is_deleted or not (record.data or {}).get("sm_spam"):
        raise SubmissionRefused(
            "not_in_trash", "only a submission in the trash as spam can be not spam"
        )
    record = await record_service.restore_record(db, rtype, record, settings=settings, actor=actor)
    record = await try_system_update(db, rtype, record, {"sm_spam": None}, settings=settings)
    await queue_notification(db, app, rtype, record)
    return record


async def _resend_confirmation(
    db: AsyncSession, app: Any, request: Any, rtype: RecordType, record: Record
) -> None:
    data = record.data or {}
    if data.get("sm_status") != PENDING:
        raise SubmissionRefused("not_pending", "only a subscriber still pending is sent one")
    settings = get_settings(request)
    wait = await budget_wait(request, rtype, str(data.get("sm_email") or ""), settings)
    if wait:
        raise SubmissionRefused(
            "rate_limited",
            "this address was sent its confirmation too often; try again later",
            headers={"Retry-After": str(wait)},
        )
    await queue_confirmation(db, app, rtype, record)


async def unsubscribe(
    db: AsyncSession, rtype: RecordType, record: Record, *, settings: RecordsSettings
) -> Record:
    """An admin's unsubscribe: what the subscriber's own link does."""
    require_subscription(rtype)
    return await opt_in.leave(db, rtype, record, settings)
