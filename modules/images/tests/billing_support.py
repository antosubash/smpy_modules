"""A stand-in for billing's ``UsageMeter`` on the storage gauge.

``conftest`` turns billing off for every test (no billing tables here): the
seam then answers as on a host without billing. ``gauge`` installs this fake
instead - the hold calls (``sm_images.billing.storage_meter``) and the web
pre-flight (``app.state.billing_usage``) - so a test can set a limit, read
what is held, and make billing fail (``fail_swap``, ``fail_release``).

Its ``swap`` is billing's: one atomic step (no ``await`` between the check
and the write), the limit on the net delta, a replayed key returning the
same hold. :func:`assert_counted_once` is the invariant every test ends on.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

import pytest
from sm_billing.contracts.metering import (
    Allowed,
    Exceeded,
    Hold,
    HoldNotFound,
    IdempotencyConflict,
)
from sm_images import billing
from sm_images.models import BillingOp, Image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

LIVE = ("held", "committed")


@dataclass
class FakeGauge:
    limit: int | None = None
    holds: dict[str, Hold] = field(default_factory=dict)
    keys: dict[str, str | None] = field(default_factory=dict)
    """Each key's outcome: its hold, or ``None`` for a refusal."""
    calls_by_key: dict[str, tuple] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    fail_swap: int = 0
    """The next N swaps raise (billing unreachable)."""
    fail_release: int = 0
    delay: float = 0.0
    """Seconds a swap takes before billing decides: concurrent swaps interleave."""

    @property
    def level(self) -> int:
        return sum(h.quantity for h in self.holds.values() if h.status in LIVE)

    def live(self, status: str | None = None) -> list[Hold]:
        want = (status,) if status else LIVE
        return [h for h in self.holds.values() if h.status in want]

    def _set(self, hold: Hold, status: str) -> Hold:
        new = Hold(hold.id, hold.tenant_id, hold.meter, hold.quantity, status, None)
        self.holds[hold.id] = new
        return new

    async def check(self, tenant_id: str, meter: str, qty: int = 1):
        self.calls.append(("check", meter, str(qty)))
        if self.limit is not None and self.level + qty > self.limit:
            return Exceeded(self.level, self.limit, qty, None)
        return Allowed(self.level, self.limit, None)

    async def swap(self, tenant_id, meter, old_hold_id, quantity, idempotency_key, *, source):
        self.calls.append(("swap", str(old_hold_id), str(quantity), idempotency_key))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_swap:
            self.fail_swap -= 1
            raise RuntimeError("billing is down")
        call = (old_hold_id, quantity, source)
        if idempotency_key in self.keys:  # a replay: the key's outcome, for the same call
            outcome, first = self.keys[idempotency_key], self.calls_by_key[idempotency_key]
            if first != call:
                raise IdempotencyConflict(idempotency_key)
            if outcome is None:
                return Exceeded(self.level, self.limit or 0, quantity, None)
            return self.holds[outcome]
        old = self.holds.get(old_hold_id) if old_hold_id else None
        if old is not None and old.tenant_id != tenant_id:
            raise HoldNotFound(old_hold_id)
        self.calls_by_key[idempotency_key] = call
        freed = old.quantity if old is not None and old.status in LIVE else 0
        grows = quantity > freed and self.limit is not None
        if grows and self.level - freed + quantity > self.limit:
            self.keys[idempotency_key] = None  # the refusal is the key's outcome
            return Exceeded(self.level, self.limit, quantity - freed, None)
        if freed:
            self._set(old, "released")
        hold = Hold(uuid.uuid4().hex, tenant_id, meter, quantity, "committed", None)
        self.holds[hold.id] = hold
        self.keys[idempotency_key] = hold.id
        return hold

    async def get_hold(self, tenant_id: str, hold_id: str) -> Hold | None:
        self.calls.append(("get_hold", hold_id))
        hold = self.holds.get(hold_id)
        return None if hold is None or hold.tenant_id != tenant_id else hold

    async def release(self, hold_id: str) -> bool:
        self.calls.append(("release", hold_id))
        if self.fail_release:
            self.fail_release -= 1
            raise RuntimeError("billing is down")
        hold = self.holds.get(hold_id)
        if hold is None:
            raise HoldNotFound(hold_id)
        if hold.status not in LIVE:
            return False
        self._set(hold, "released")
        return True


@pytest.fixture(autouse=True)
def _billing_off():
    """Every test runs as on a host without billing unless it asks for ``gauge``.
    Its own patcher: a test's ``monkeypatch.undo()`` must not turn billing on."""
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(billing, "billing_installed", lambda: False)
        yield


@pytest.fixture
def gauge(monkeypatch) -> FakeGauge:
    fake = FakeGauge()
    monkeypatch.setattr(billing, "storage_meter", lambda factory: fake)
    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    return fake


async def ops(db_state) -> list:
    """Every outbox row, oldest first."""
    async with db_state.session_factory() as s:
        return list((await s.execute(select(BillingOp).order_by(BillingOp.id))).scalars())


async def held_image(pipe, gauge, coll):
    """An ingested image: its original under a committed hold, as ingest leaves it."""
    img = await pipe.image(coll)
    row = await pipe.row(img)
    hold = await gauge.swap(DEFAULT_TENANT, billing.METER, None, row.size_bytes, "seed", source="t")
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == img)
            .values(storage_hold_id=hold.id, storage_bytes=row.size_bytes)
        )
        await s.commit()
    return img, hold.id


async def assert_counted_once(db_state, gauge) -> None:
    """The invariant: no op pending, and every image (trashed included) is
    counted by exactly one live hold - the one it names, of its
    ``storage_bytes`` - and nothing else is held."""
    async with db_state.session_factory() as s:
        images = (
            await s.execute(
                select(Image.storage_hold_id, Image.storage_bytes).execution_options(
                    include_deleted=True
                )
            )
        ).all()
        pending = (await s.execute(select(BillingOp).where(BillingOp.done_at.is_(None)))).all()
    assert pending == []
    named = {hold: size for hold, size in images if hold is not None}
    assert len(named) == len(images)
    assert {h.id: h.quantity for h in gauge.live()} == named
    assert all(h.status == "committed" for h in gauge.live())
