"""A key's terminal outcome: reading it, and ``close_key``.

Every ``(tenant, meter, idempotency_key)`` of a gauge ends with exactly one
outcome, committed in the transaction that claimed the key (the unique row on
``billing_usage_hold`` is the admission lock): a ``Hold`` (``committed``, then
perhaps ``released``), a refusal (``refused``), a call past its deadline
(``expired_call``) or a closure (``closed``).

``close_key`` is how a consumer finishes its own record of a call without one
of its own: if the key has an outcome it returns it; otherwise it commits
``Closed``, and from then on every ``swap`` under the key answers ``Closed``
and writes nothing. A swap still in flight holds the key's row until it
commits, so a ``close_key`` behind it waits on the unique index (Postgres; on
SQLite the writer lock) and then returns that swap's outcome. A closed key is
a ``billing_usage_hold`` row with status ``closed``, quantity 0, source
``close_key`` and no deadline: key-wide, counted by nothing, settled when
closed, and purged by retention like the other settled rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select, update

from sm_billing.contracts.metering import Closed, Expired, Hold, HoldStatus, MeterKind, Refused
from sm_billing.metering import dbtime, hold_sql
from sm_billing.metering.holds import HoldsMixin, _hold
from sm_billing.metering.periods import as_utc
from sm_billing.metering.tx import Terminal, run_write
from sm_billing.metering.validate import KEY_MAX, METER_MAX, TENANT_MAX, check_text
from sm_billing.models import UsageHold

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_REPLAY = "replay"
#: Claims tried before giving up: a conflicting row purged between our claim
#: and our read of it leaves the key free, and the next claim takes it.
CLAIM_TRIES = 3
CLOSE_SOURCE = "close_key"
_ROW = (
    *hold_sql.HOLD_COLUMNS,
    UsageHold.source,
    UsageHold.replaces_hold_id,
    UsageHold.refused_used,
    UsageHold.refused_limit,
    UsageHold.refused_requested,
    UsageHold.not_after,
)


def settle_claim(hold_id: str, at: datetime, status: str, **fields: Any) -> Any:
    """Turn the claim row into the key's terminal outcome ``status`` (counted by
    nothing), settled ``at`` (database time)."""
    hold = hold_sql.HOLD
    return update(hold).where(hold.c.id == hold_id).values(status=status, settled_at=at, **fields)


def utc_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else as_utc(value)


class ClosingMixin(HoldsMixin):
    """Key outcomes on top of the gauge holds."""

    async def _key_row(self, tenant_id: str, meter: str, idempotency_key: str) -> Any:
        """The key's row, read in a fresh session (so on Postgres with a fresh
        snapshot: a conflicting claim that committed after ours began is seen)."""
        async with self._factory() as session:
            stmt = select(*_ROW).where(
                UsageHold.tenant_id == tenant_id,
                UsageHold.meter == meter,
                UsageHold.idempotency_key == idempotency_key,
            )
            return (await session.execute(stmt)).one_or_none()

    async def close_key(
        self, tenant_id: str, meter: str, idempotency_key: str
    ) -> Hold | Refused | Expired | Closed:
        check_text("tenant_id", tenant_id, TENANT_MAX)
        check_text("meter", meter, METER_MAX)
        check_text("idempotency_key", idempotency_key, KEY_MAX)
        self._require(meter, MeterKind.GAUGE)
        values = {
            "id": uuid4().hex,
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": 0,
            "status": HoldStatus.CLOSED.value,
            "idempotency_key": idempotency_key,
            "expires_at": None,
            "created_at": self._clock(),
            "source": CLOSE_SOURCE,
        }

        async def apply(session: AsyncSession) -> Terminal | str:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(hold_sql.insert_hold(dialect, **values))
            if claimed.scalar_one_or_none() is None:
                return _REPLAY
            at = await dbtime.now(session)
            await session.execute(settle_claim(values["id"], at, HoldStatus.CLOSED.value))
            return Terminal(Closed(idempotency_key))

        for _ in range(CLAIM_TRIES):
            outcome = await run_write(self._factory, None, apply)
            if isinstance(outcome, Terminal):
                return outcome.outcome
            row = await self._key_row(tenant_id, meter, idempotency_key)
            if row is not None:
                return key_outcome(row, idempotency_key)
        raise RuntimeError(f"billing: key {idempotency_key!r} could not be claimed or read")


def key_outcome(row: Any, key: str) -> Hold | Refused | Expired | Closed:
    """What ``close_key`` answers for a key's recorded outcome."""
    if row.status == HoldStatus.CLOSED.value:
        return Closed(key)
    if row.status == HoldStatus.REFUSED.value:
        return Refused(key)
    if row.status == HoldStatus.EXPIRED_CALL.value:
        return Expired(key, as_utc(row.not_after))
    return _hold(row)
