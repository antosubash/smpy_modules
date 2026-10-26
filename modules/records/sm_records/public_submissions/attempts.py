"""A delivery attempt's fixed recipient set, and its completion (#101).

An attempt is one queued notification or confirmation (``NotificationDue.
attempt``); a *Resend* is a new attempt. Its recipients are decided **once**,
when the attempt first runs, and persisted: :func:`manifest` writes, in one
transaction, a manifest row (recipient :data:`MANIFEST`) and one *pending*
row per recipient key (no claim, not sent). Every retry of the attempt then
works from those rows — never from the type's current ``notify_to``. An admin
who adds or removes a recipient changes the next attempt, not one already
underway, so an attempt can never finish against a different set from the
one it started with.

:func:`complete` stamps the attempt finished with a completion row
(recipient :data:`COMPLETE`), in one ``INSERT … SELECT`` that writes it only
if the manifest exists and **no recipient row of the attempt is unsent** —
the database decides, so a stale worker that lost a claim, or one that saw
only part of the set, cannot stamp it. Pruning trusts that row
(:mod:`.retention_deliveries`).

No recipient key can collide with the two markers: staff keys are addresses
and subscriber keys are ``h:`` + hex, and no claim is ever made for a marker.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import DateTime, bindparam, select, text
from sqlalchemy.exc import IntegrityError

from sm_records import events
from sm_records.models import SubmissionDelivery
from sm_records.models._delivery import DELIVERY_TABLE
from sm_records.public_submissions.delivery import SessionFactory, Slot, _alive
from sm_records.services._common import utcnow

__all__ = ["COMPLETE", "MANIFEST", "MARKERS", "complete", "manifest", "recipients_of"]

MANIFEST: Final = "~attempt-manifest"
"""The marker that an attempt's recipient set has been fixed."""

COMPLETE: Final = "~attempt-complete"
"""The marker that every recipient of the attempt's fixed set is sent."""

MARKERS: Final = (MANIFEST, COMPLETE)


def _of(tenant: str, uuid: str, attempt: str) -> tuple[Any, ...]:
    table = SubmissionDelivery
    return (table.tenant_id == tenant, table.record_uuid == uuid, table.attempt == attempt)


def recipients_of(rows: Sequence[str]) -> list[str]:
    return [key for key in rows if key not in MARKERS]


async def _keys(session: Any, tenant: str, uuid: str, attempt: str) -> list[str]:
    table = SubmissionDelivery
    stmt = select(table.recipient).where(*_of(tenant, uuid, attempt)).order_by(table.id)
    return [str(key) for key in (await session.execute(stmt)).scalars().all()]


async def manifest(
    factory: SessionFactory,
    tenant: str,
    uuid: str,
    attempt: str,
    keys: Sequence[str],
    record: Any = None,
) -> list[str] | None:
    """The attempt's fixed recipient keys: the persisted set when the attempt
    has one, else ``keys``, persisted now. ``None`` when the record is gone
    (``record`` is its table class, checked under a share lock as a claim is).

    An attempt that began before manifests existed has recipient rows but no
    manifest: its set is those rows plus ``keys``, fixed from here on."""
    for _ in range(3):
        session = factory()
        try:
            if not await _alive(session, record, Slot(tenant, uuid, attempt, MANIFEST)):
                await events.rollback(session)
                return None
            present = await _keys(session, tenant, uuid, attempt)
            if MANIFEST in present:
                await events.rollback(session)
                return recipients_of(present)
            now = utcnow()
            missing = [key for key in dict.fromkeys(keys) if key not in present]
            session.add(
                SubmissionDelivery(
                    tenant_id=tenant,
                    record_uuid=uuid,
                    attempt=attempt,
                    recipient=MANIFEST,
                    sent_at=now,
                )
            )
            for key in missing:
                session.add(
                    SubmissionDelivery(
                        tenant_id=tenant, record_uuid=uuid, attempt=attempt, recipient=key
                    )
                )
            try:
                await events.commit(session)
            except IntegrityError:
                await events.rollback(session)  # another worker fixed it first: re-read
                continue
            return recipients_of([*present, *missing])
        finally:
            await session.close()
    raise RuntimeError(f"could not fix the recipients of attempt {attempt} for {uuid}")


_COMPLETE_SQL: Final = f"""
INSERT INTO {DELIVERY_TABLE} (tenant_id, record_uuid, attempt, recipient, sent_at)
SELECT CAST(:tenant AS VARCHAR), CAST(:uuid AS VARCHAR), CAST(:attempt AS VARCHAR),
       CAST(:complete AS VARCHAR), :now
WHERE EXISTS (
    SELECT 1 FROM {DELIVERY_TABLE}
    WHERE tenant_id = :tenant AND record_uuid = :uuid AND attempt = :attempt
      AND recipient = :manifest
)
AND NOT EXISTS (
    SELECT 1 FROM {DELIVERY_TABLE}
    WHERE tenant_id = :tenant AND record_uuid = :uuid AND attempt = :attempt
      AND recipient NOT IN (:manifest, :complete) AND sent_at IS NULL
)
"""
"""One statement, so the check and the write see the same rows: the marker
lands only beside a manifest and with no recipient of the attempt unsent."""


async def complete(factory: SessionFactory, tenant: str, uuid: str, attempt: str) -> bool:
    """Stamp ``attempt`` complete if — and only if, as the database sees it
    in this one statement — its manifest exists and none of its recipients is
    unsent. ``True`` when the attempt is (now, or already) complete."""
    # Text, not a Core ``insert().from_select``: the framework's tenancy
    # listener stamps ``tenant_id`` onto Core inserts with ``.values()``,
    # which an INSERT … SELECT cannot take. The tenant is in every clause.
    stmt = text(_COMPLETE_SQL).bindparams(
        bindparam("now", type_=DateTime(timezone=True)),
    )
    params = {
        "tenant": tenant,
        "uuid": uuid,
        "attempt": attempt,
        "complete": COMPLETE,
        "manifest": MANIFEST,
        "now": utcnow(),
    }
    session = factory()
    try:
        try:
            result = await session.execute(stmt, params)
            await events.commit(session)
            if result.rowcount == 1:
                return True
        except IntegrityError:
            await events.rollback(session)
        return COMPLETE in await _keys(session, tenant, uuid, attempt)
    finally:
        await session.close()
