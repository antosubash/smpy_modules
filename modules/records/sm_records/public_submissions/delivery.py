"""One delivery attempt of a submission's notification, recipient by recipient.

SMTP cannot be made exactly-once, but a retry must not mail a recipient whose
send went through, and two outbox workers running one attempt must not both
send. So every recipient of an attempt is **claimed** first, in the internal
``records_submission_delivery`` table, whose unique key
``(tenant, record, attempt, recipient)`` makes the claim the database's
decision — an ``INSERT``, or for a row a crashed worker left behind, a
conditional ``UPDATE`` that takes over a claim older than :data:`LEASE`. A
claim, a release and a "sent" each commit in a session of their own, so a
rollback of the caller's transaction (the outbox's ``ctx.db``, or the
after-commit task's session) never loses them.

* A row with ``sent_at`` is never sent again.
* Every claim carries an ownership token. Releasing it and marking it sent
  are conditional on the token, so a worker that stalled past its lease
  cannot clear or complete the claim its successor took over.
* A send that raises — or outlasts :data:`SEND_TIMEOUT`, far below the lease
  — releases its claim so the retry takes it at once; a crash leaves it to
  expire.

**The residual window.** SMTP cannot be made exactly-once: a message the
server accepted, followed by a crash (or a stall past the lease) before
``sent_at`` is written, is sent again by whoever takes the claim over. That
window is one send long, and nothing else re-mails a recipient. It opens
without a crash too: a send cancelled mid-SMTP by :data:`SEND_TIMEOUT`, after
the server may already have accepted the message, is retried. And
``asyncio.wait_for`` is not a hard wall-clock cap — it awaits the cancelled
send's cleanup — so a send can outlast the timeout by that much.
* A recipient claimed by another worker, still inside its lease, raises
  :class:`DeliveryInProgress`: the outbox retries later, and the record is not
  marked notified until every recipient is sent.

The attempt is ``NotificationDue.attempt``, minted when the notification is
queued, so an explicit *Resend* is a new attempt that reaches everyone again.
An event queued without one gets a stable id derived from its own payload
(:func:`attempt_of`) — the outbox's ``DurableContext`` does not expose the
event's row id.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Literal

from simple_module_core.mail import MailSender
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType, SubmissionDelivery
from sm_records.services._common import utcnow
from sm_records.services.errors import NotFound
from sm_records.services.records import get_record
from sm_records.services.types import get_type

__all__ = [
    "LEASE",
    "SEND_TIMEOUT",
    "DeliveryInProgress",
    "Slot",
    "attempt_of",
    "claim",
    "load",
    "mark_sent",
    "release",
]

logger = logging.getLogger(__name__)

LEASE: Final = timedelta(minutes=10)
"""How long a claim that was never marked sent blocks everyone else."""

SEND_TIMEOUT: Final = timedelta(seconds=60)
"""How long one send may take before it counts as failed — well under
:data:`LEASE`, so a live worker's claim never expires while it is sending.
The framework's ``MailSender.send`` takes no timeout of its own."""

SessionFactory = Callable[[], AsyncSession]
Claim = Literal["claimed", "sent", "busy", "gone"]


class DeliveryInProgress(RuntimeError):  # noqa: N818 - reads as the condition it is
    """Another worker holds a live claim on a recipient of this attempt."""


def attempt_of(due: Any) -> str:
    if due.attempt:
        return str(due.attempt)
    raw = "|".join((due.tenant_id, due.type_key, due.uuid, due.base_url, due.locale))
    return "legacy-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


async def load(db: AsyncSession, due: Any) -> tuple[RecordType, Record] | None:
    """The type and the live record, or ``None`` when either has gone — a
    record trashed or purged before its mail went out is not mailed."""
    try:
        rtype = await get_type(db, due.type_key)
        return rtype, await get_record(db, rtype, due.uuid)
    except NotFound:
        logger.info("records: %s submission %s is gone; not mailed", due.type_key, due.uuid)
        return None


def _key(tenant: str, uuid: str, attempt: str, recipient: str) -> tuple[Any, ...]:
    table = SubmissionDelivery
    return (
        table.tenant_id == tenant,
        table.record_uuid == uuid,
        table.attempt == attempt,
        table.recipient == recipient,
    )


async def _apply(factory: SessionFactory, stmt: Any) -> int:
    session = factory()
    try:
        result = await session.execute(stmt)
        await events.commit(session)
        return int(result.rowcount or 0)
    finally:
        await session.close()


@dataclass(frozen=True)
class Slot:
    """One recipient of one attempt: the unique key of a delivery row."""

    tenant: str
    uuid: str
    attempt: str
    recipient: str

    def where(self) -> tuple[Any, ...]:
        return _key(self.tenant, self.uuid, self.attempt, self.recipient)


async def _alive(session: AsyncSession, record: Any, slot: Slot) -> bool:
    """Whether the record still exists (live), holding a share lock on its row
    until the claim's transaction ends. A purge takes ``FOR UPDATE`` on the
    same row before it deletes the record's claims, so the two serialise:
    either the claim commits first and the purge deletes it, or the purge
    commits first and this finds no row. (SQLite's single writer serialises
    them without the lock.)"""
    if record is None:
        return True
    stmt = (
        select(record.id)
        .where(record.uuid == slot.uuid, record.tenant_id == slot.tenant)
        .with_for_update(read=True)
    )
    return (await session.execute(stmt)).first() is not None


async def claim(
    factory: SessionFactory, slot: Slot, record: Any = None
) -> tuple[Claim, str | None]:
    """Take ``slot``, or say why not. A claim comes with an ownership token:
    only its holder may release it or mark it sent. With ``record`` (the
    record's table class) a claim is only ever made while that record exists:
    ``"gone"`` once it has been purged or trashed, and nothing is sent."""
    now, token = utcnow(), secrets.token_hex(16)
    session = factory()
    try:
        if not await _alive(session, record, slot):
            await events.rollback(session)
            return "gone", None
        session.add(
            SubmissionDelivery(
                tenant_id=slot.tenant,
                record_uuid=slot.uuid,
                attempt=slot.attempt,
                recipient=slot.recipient,
                claimed_at=now,
                claim_token=token,
            )
        )
        try:
            await events.commit(session)
            return "claimed", token
        except IntegrityError:
            await events.rollback(session)
        if not await _alive(session, record, slot):
            await events.rollback(session)
            return "gone", None
        table = SubmissionDelivery
        expired = or_(table.claimed_at.is_(None), table.claimed_at < now - LEASE)
        take = update(table).where(*slot.where(), table.sent_at.is_(None), expired)
        result = await session.execute(take.values(claimed_at=now, claim_token=token))
        await events.commit(session)
        if result.rowcount == 1:
            return "claimed", token
        sent = await session.execute(select(table.sent_at).where(*slot.where()))
        return ("sent" if sent.scalar_one_or_none() is not None else "busy"), None
    finally:
        await session.close()


def _mine(slot: Slot, token: str) -> Any:
    table = SubmissionDelivery
    return update(table).where(*slot.where(), table.claim_token == token, table.sent_at.is_(None))


async def release(factory: SessionFactory, slot: Slot, token: str) -> bool:
    """Give the claim back after a failed send — only if it is still ours: a
    worker whose lease expired must not clear its successor's claim."""
    return await _apply(factory, _mine(slot, token).values(claimed_at=None, claim_token=None)) == 1


async def mark_sent(factory: SessionFactory, slot: Slot, token: str) -> bool:
    """Record the send — only if the claim is still ours. ``False`` means the
    lease ran out mid-send and another worker took the recipient over."""
    return await _apply(factory, _mine(slot, token).values(sent_at=utcnow())) == 1


async def _send_one(
    factory: SessionFactory, slot: Slot, token: str, sender: MailSender, message: Any
) -> None:
    try:
        await asyncio.wait_for(sender.send(message), SEND_TIMEOUT.total_seconds())
    except BaseException:
        await release(factory, slot, token)
        raise
    if not await mark_sent(factory, slot, token):
        logger.warning(
            "records: the claim on %s for %s expired mid-send; it may be mailed twice",
            slot.recipient,
            slot.uuid,
        )
