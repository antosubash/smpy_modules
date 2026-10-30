"""``swap``: replace a gauge hold with a committed one in one transaction.

A consumer that keeps one hold per resource (``images`` holds each image's
stored bytes) must move that hold when the resource's size changes. Done as
two calls - reserve and commit the new hold, then release the old - the
consumer has to choose an order, and either one leaves a window: release
first and the resource is counted by nothing until the new hold fits; reserve
first and it is counted twice, which near the limit refuses a resize that
would fit. ``swap`` does it in one transaction:

1. claim the key with a new hold, ``committed`` (no expiry) from the start;
2. release the old hold - only one of the tenant's own, on the same meter,
   still live (a ``held`` hold past its expiry still counts in the gauge, so
   it is freed too); an old hold already settled, or unknown, frees nothing
   and the call is a plain reserve and commit;
3. raise the level by the new quantity within the limit, after the old one
   was taken off: the check is on the net delta. A delta of zero or less is
   admitted even over the limit (a plan lowered under the tenant must not stop
   a resource from shrinking).

**One transaction per key, through commit.** The key's row on
``billing_usage_hold`` is the admission lock: the call claims it first, then
reads the time *from the database* (``dbtime``) and only then decides. Past
``not_after``, the claim becomes ``expired_call`` and nothing else is written.
Otherwise steps 2-3 run in a SAVEPOINT; a refusal rolls them back - the old
hold still counts - and turns the claim into ``refused``, in the same
transaction. So every key ends with exactly one committed outcome (the hold,
``refused``, ``expired_call``, or ``closed`` by ``close_key``), and no call
can mutate under a key whose outcome another committed, however long it was
paused: once retention purged that outcome, its claim succeeds but the
database's clock is past its deadline (retention keeps a row until a day past
its ``not_after``).

A call whose claim conflicts reads the key's outcome afresh (Postgres: a new
statement, a new snapshot - a concurrent claim was waited on by the unique
index, and is committed by then). ``Closed`` answers any call; otherwise a
replay must be the same call - quantity, source, old hold *and* deadline -
else ``IdempotencyConflict``, and it returns the outcome as first answered.
On Postgres two swaps of one old hold serialise on its row: the second finds
it settled and has to fit its whole quantity.

Lock order: the key's row, then the old hold, then the gauge (as ``release``:
hold before gauge).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select, update

from sm_billing.contracts.metering import (
    LIVE_HOLD_STATUSES,
    Closed,
    Exceeded,
    Expired,
    Hold,
    HoldNotFound,
    HoldStatus,
    IdempotencyConflict,
    MeterKind,
)
from sm_billing.metering import dbtime, hold_sql
from sm_billing.metering.closing import CLAIM_TRIES, ClosingMixin, settle_claim, utc_or_none
from sm_billing.metering.holds import _hold
from sm_billing.metering.periods import as_utc
from sm_billing.metering.tx import Terminal, run_write
from sm_billing.metering.validate import check_call, check_hold_id
from sm_billing.models import UsageGauge, UsageHold

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_REPLAY, _FOREIGN = "replay", "foreign"


class _Foreign(Exception):  # noqa: N818 - control flow, never escapes this module
    """The old hold is another tenant's or meter's."""


class _NoRoom(Exception):  # noqa: N818 - control flow, never escapes this module
    """The new level would pass the limit; ``freed`` is what the old hold held."""

    def __init__(self, freed: int) -> None:
        super().__init__(freed)
        self.freed = freed


def _release_old(old: str, tenant_id: str, meter: str, now: datetime) -> Any:
    hold = hold_sql.HOLD
    return (
        update(hold)
        .where(
            hold.c.id == old,
            hold.c.tenant_id == tenant_id,
            hold.c.meter == meter,
            hold.c.status.in_(sorted(LIVE_HOLD_STATUSES)),
        )
        .values(status=HoldStatus.RELEASED.value, settled_at=now)
        .returning(hold.c.quantity)
    )


class SwapMixin(ClosingMixin):
    """``swap`` on top of the gauge holds and the key outcomes."""

    async def swap(
        self,
        tenant_id: str,
        meter: str,
        old_hold_id: str | None,
        quantity: int,
        idempotency_key: str,
        *,
        source: str,
        not_after: datetime,
    ) -> Hold | Exceeded | Expired | Closed:
        check_call(tenant_id, meter, quantity, idempotency_key, source)
        if old_hold_id is not None:
            check_hold_id(old_hold_id)
        self._require(meter, MeterKind.GAUGE)
        limit = (await self._resolve(tenant_id, meter, None)).limit
        deadline = as_utc(not_after)
        values = {
            "id": uuid4().hex,
            "tenant_id": tenant_id,
            "meter": meter,
            "quantity": quantity,
            "status": HoldStatus.COMMITTED.value,
            "idempotency_key": idempotency_key,
            "expires_at": None,
            "created_at": self._clock(),
            "source": source,
            "replaces_hold_id": old_hold_id,
            "not_after": deadline,
        }

        async def apply(session: AsyncSession) -> Terminal | str:
            dialect = session.get_bind().dialect.name
            claimed = await session.execute(hold_sql.insert_hold(dialect, **values))
            if claimed.scalar_one_or_none() is None:
                return _REPLAY
            at = await dbtime.now(session)  # admission time: read after the claim
            if at > deadline:  # the caller's deadline passed: nothing may change
                status = HoldStatus.EXPIRED_CALL.value
                await session.execute(settle_claim(values["id"], at, status))
                return Terminal(Expired(idempotency_key, deadline))
            return await self._admit(session, values, limit, at)

        for _ in range(CLAIM_TRIES):
            outcome = await run_write(self._factory, None, apply)
            if isinstance(outcome, Terminal):
                return outcome.outcome
            if outcome == _FOREIGN:
                raise HoldNotFound(old_hold_id or "")
            replayed = await self._replay_swap(values)
            if replayed is not None:
                return replayed
        raise IdempotencyConflict(idempotency_key)

    async def _admit(
        self, session: AsyncSession, values: dict, limit: int | None, at: datetime
    ) -> Terminal | str:
        """Steps 2-3 in a SAVEPOINT; the claim becomes the key's outcome."""
        tenant_id, meter, quantity = values["tenant_id"], values["meter"], values["quantity"]
        try:
            async with session.begin_nested():  # a refusal rolls back to here
                await self._move(session, values, limit, at)
        except _Foreign:
            return _FOREIGN  # rolls the claim back too: nothing is written
        except _NoRoom as no_room:  # the old hold still counts
            level = select(UsageGauge.in_use).where(
                UsageGauge.tenant_id == tenant_id, UsageGauge.meter == meter
            )
            used = int((await session.execute(level)).scalar_one_or_none() or 0)
            refused = Exceeded(used, limit or 0, quantity - no_room.freed, None)
            fields = {"refused_" + k: getattr(refused, k) for k in ("used", "limit", "requested")}
            status = HoldStatus.REFUSED.value
            await session.execute(settle_claim(values["id"], at, status, **fields))
            return Terminal(refused)
        committed = HoldStatus.COMMITTED.value
        return Terminal(Hold(values["id"], tenant_id, meter, quantity, committed, None))

    async def _move(
        self, session: AsyncSession, values: dict, limit: int | None, at: datetime
    ) -> int:
        """Release the old hold and raise the level (the freed quantity), or
        raise to roll the SAVEPOINT back."""
        tenant_id, meter, quantity = values["tenant_id"], values["meter"], values["quantity"]
        old, freed = values["replaces_hold_id"], 0
        if old is not None:
            row = (await session.execute(_release_old(old, tenant_id, meter, at))).first()
            if row is not None:
                freed = int(row.quantity)
                await session.execute(
                    hold_sql.lower_gauge(tenant_id=tenant_id, meter=meter, qty=freed, now=at)
                )
            elif await self._foreign(session, old, tenant_id, meter):
                raise _Foreign
        fields = {"tenant_id": tenant_id, "meter": meter, "qty": quantity, "now": at}
        bound = None if quantity <= freed else limit  # a shrink is never refused
        if bound is not None and quantity > bound:
            stmt = hold_sql.raise_within_limit(**fields, limit=bound)
        else:
            dialect = session.get_bind().dialect.name
            stmt = hold_sql.upsert_gauge(dialect, **fields, limit=bound)
        if (await session.execute(stmt)).scalar_one_or_none() is None:
            raise _NoRoom(freed)
        return freed

    async def _replay_swap(self, call: dict) -> Hold | Exceeded | Expired | Closed | None:
        """The outcome recorded under ``call``'s key, if it is the same call
        (any call, for a closed key); ``None`` when no row is there (purged
        since the claim conflicted: the key is free again)."""
        key = call["idempotency_key"]
        row = await self._key_row(call["tenant_id"], call["meter"], key)
        if row is None:
            return None
        if row.status == HoldStatus.CLOSED.value:  # key-wide: no fingerprint
            return Closed(key)
        same = (int(row.quantity), row.source, row.replaces_hold_id, utc_or_none(row.not_after))
        if same != (call["quantity"], call["source"], call["replaces_hold_id"], call["not_after"]):
            raise IdempotencyConflict(key)
        if row.status == HoldStatus.REFUSED.value:  # as first answered
            used, limit, requested = row.refused_used, row.refused_limit, row.refused_requested
            return Exceeded(int(used), int(limit), int(requested), None)
        if row.status == HoldStatus.EXPIRED_CALL.value:
            return Expired(key, as_utc(row.not_after))
        return _hold(row, replayed=True)

    @staticmethod
    async def _foreign(session: AsyncSession, hold_id: str, tenant_id: str, meter: str) -> bool:
        """``hold_id`` exists but belongs to another tenant or meter."""
        stmt = select(UsageHold.tenant_id, UsageHold.meter).where(UsageHold.id == hold_id)
        row = (await session.execute(stmt)).first()
        return row is not None and (row.tenant_id, row.meter) != (tenant_id, meter)
