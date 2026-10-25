"""Sending one attempt's messages through the claims of :mod:`.delivery`.

Split from :mod:`.delivery` for the 300-line cap: that module owns the claim
protocol (claim, release, mark sent, the lease and the send timeout), this
one walks an attempt's recipients through it and writes the record's mark.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from simple_module_core.mail import MailSender
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions import delivery
from sm_records.public_submissions.delivery import SessionFactory
from sm_records.public_submissions.system import try_system_update
from sm_records.settings import RecordsSettings

__all__ = ["send_all"]

logger = logging.getLogger(__name__)


async def send_all(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    sender: MailSender,
    due: Any,
    settings: RecordsSettings,
    factory: SessionFactory,
    messages: list[tuple[str, Any]],
    mark: Callable[[], dict[str, Any]],
) -> None:
    """Mail every recipient this attempt has not reached, then write ``mark()``
    onto the record. ``messages`` are ``(recipient key, message)``: the key
    names the recipient in the claims table — the address for staff, a keyed
    hash for a subscriber — and the message carries the address. A failed
    send is raised once every recipient has been tried; the ones that went
    through stay sent."""
    tenant, attempt, busy = rtype.tenant_id, delivery.attempt_of(due), False
    failure: Exception | None = None
    table = tables_for(rtype).record
    for to, message in messages:
        slot = delivery.Slot(tenant, record.uuid, attempt, to)
        state, token = await delivery.claim(factory, slot, table)
        if state == "gone":
            logger.info("records: %s record %s is gone; not mailed", rtype.key, record.uuid)
            return
        if state != "claimed" or token is None:
            busy = busy or state == "busy"
            continue
        try:
            await delivery._send_one(factory, slot, token, sender, message)
        except Exception as exc:
            # One address the transport refuses must not keep the recipients
            # after it from ever being mailed: carry on, then fail the attempt.
            logger.warning("records: mailing %s for %s failed: %s", to, record.uuid, exc)
            failure = failure or exc
    if failure is not None:
        raise failure
    if busy:
        raise delivery.DeliveryInProgress(
            f"another worker is still mailing submission {record.uuid}"
        )
    await try_system_update(db, rtype, record, mark(), settings=settings)
