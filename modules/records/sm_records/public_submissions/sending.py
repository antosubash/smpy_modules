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
from sm_records.public_submissions import attempts, delivery
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
    build: Callable[[str], Any] | None = None,
) -> None:
    """Mail every recipient of this attempt's **fixed** set it has not
    reached, stamp the attempt complete, then write ``mark()`` onto the
    record.

    ``messages`` are ``(recipient key, message)`` as the attempt would be
    built now: the key names the recipient in the claims table — the address
    for staff, a keyed hash for a subscriber. The first run persists those
    keys as the attempt's set (:func:`.attempts.manifest`); a retry works from
    the persisted set, building a message for a key no longer in ``messages``
    with ``build`` (an address an admin has since removed is still owed this
    attempt's mail). A failed send — a lost claim included — is raised once
    every recipient has been tried; the ones that went through stay sent."""
    tenant, attempt, busy = rtype.tenant_id, delivery.attempt_of(due), False
    failure: Exception | None = None
    table = tables_for(rtype).record
    current = dict(messages)
    keys = await attempts.manifest(factory, tenant, record.uuid, attempt, list(current), table)
    if keys is None:
        logger.info("records: %s record %s is gone; not mailed", rtype.key, record.uuid)
        return
    for to in keys:
        message = current.get(to)
        if message is None and build is not None:
            message = build(to)
        if message is None:
            failure = failure or RuntimeError(f"no message for recipient {to} of {record.uuid}")
            continue
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
    # The database confirms every recipient of the fixed set is sent before
    # it stamps the attempt: a recipient another worker still holds keeps it
    # open, and so does a stale worker's view of the set.
    if busy or not await attempts.complete(factory, tenant, record.uuid, attempt):
        raise delivery.DeliveryInProgress(
            f"another worker is still mailing submission {record.uuid}"
        )
    await try_system_update(db, rtype, record, mark(), settings=settings)
