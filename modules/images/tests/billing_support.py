"""A stand-in for billing's ``UsageMeter`` on the storage gauge.

``conftest`` turns billing off for every test (no billing tables here): the
seam then answers as on a host without billing. ``gauge`` installs this fake
instead - the hold calls (``sm_images.billing.storage_meter``) and the web
pre-flight (``app.state.billing_usage``) - so a test can set a limit, read
what is held, and make billing fail (``fail_commit``, ``fail_release``, ``expire_on_commit``,
``next_seconds``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sm_billing.contracts.metering import Allowed, Exceeded, Hold, HoldExpired
from sm_images import billing
from sm_images.models import Image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

LIVE = ("held", "committed")
DEFAULT_TTL = 900


@dataclass
class FakeGauge:
    limit: int | None = None
    holds: dict[str, Hold] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    ttls: list[int | None] = field(default_factory=list)
    fail_commit: int = 0
    """The next N commits raise (billing unreachable)."""
    fail_release: int = 0
    expire_on_commit: int = 0
    """The next N commits find their hold lapsed (``HoldExpired``)."""
    next_seconds: list[int] = field(default_factory=list)
    """TTLs (seconds) the next reservations get instead of the one asked for."""

    @property
    def level(self) -> int:
        return sum(h.quantity for h in self.holds.values() if h.status in LIVE)

    def live(self, status: str | None = None) -> list[Hold]:
        want = (status,) if status else LIVE
        return [h for h in self.holds.values() if h.status in want]

    def _set(self, hold: Hold, status: str, expires_at: datetime | None = None) -> Hold:
        new = Hold(hold.id, hold.tenant_id, hold.meter, hold.quantity, status, expires_at)
        self.holds[hold.id] = new
        return new

    def expire(self, hold_id: str) -> None:
        self._set(self.holds[hold_id], "expired")

    def _lapse(self, hold: Hold) -> Hold:
        if hold.status == "held" and hold.expires_at and hold.expires_at <= datetime.now(UTC):
            return self._set(hold, "expired")
        return hold

    async def check(self, tenant_id: str, meter: str, qty: int = 1):
        self.calls.append(("check", meter, str(qty)))
        if self.limit is not None and self.level + qty > self.limit:
            return Exceeded(self.level, self.limit, qty, None)
        return Allowed(self.level, self.limit, None)

    async def reserve(self, tenant_id, meter, qty, idempotency_key, *, source, ttl=None):
        self.calls.append(("reserve", meter, str(qty), idempotency_key))
        self.ttls.append(ttl)
        if idempotency_key in self.keys:
            return self.holds[self.keys[idempotency_key]]
        if self.limit is not None and self.level + qty > self.limit:
            return Exceeded(self.level, self.limit, qty, None)
        seconds = self.next_seconds.pop(0) if self.next_seconds else (ttl or DEFAULT_TTL)
        expires = datetime.now(UTC) + timedelta(seconds=seconds)
        hold = Hold(uuid.uuid4().hex, tenant_id, meter, qty, "held", expires)
        self.holds[hold.id] = hold
        self.keys[idempotency_key] = hold.id
        return hold

    async def commit(self, hold_id: str) -> Hold:
        self.calls.append(("commit", hold_id))
        if self.fail_commit:
            self.fail_commit -= 1
            raise RuntimeError("billing is down")
        hold = self._lapse(self.holds[hold_id])
        if self.expire_on_commit and hold.status == "held":
            self.expire_on_commit -= 1
            hold = self._set(hold, "expired")
        if hold.status not in LIVE:
            raise HoldExpired(hold_id, hold.status)
        return self._set(hold, "committed")

    async def extend(self, hold_id: str, ttl: int) -> Hold:
        self.calls.append(("extend", hold_id, str(ttl)))
        hold = self._lapse(self.holds[hold_id])
        if hold.status != "held":
            raise HoldExpired(hold_id, hold.status)
        return self._set(hold, "held", datetime.now(UTC) + timedelta(seconds=ttl))

    async def release(self, hold_id: str) -> bool:
        self.calls.append(("release", hold_id))
        if self.fail_release:
            self.fail_release -= 1
            raise RuntimeError("billing is down")
        hold = self.holds.get(hold_id)
        if hold is None or hold.status not in LIVE:
            return False
        self._set(hold, "released")
        return True


@pytest.fixture(autouse=True)
def _billing_off():
    """Every test runs as on a host without billing unless it asks for ``gauge``.
    Its own patcher: a test's ``monkeypatch.undo()`` must not turn billing on."""
    from sm_images import billing

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(billing, "billing_installed", lambda: False)
        yield


@pytest.fixture
def gauge(monkeypatch) -> FakeGauge:
    from sm_images import billing

    fake = FakeGauge()
    monkeypatch.setattr(billing, "storage_meter", lambda factory: fake)
    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    return fake


async def ops(db_state) -> list:
    """Every outbox row, oldest first."""
    from sm_images.models import BillingOp
    from sqlalchemy import select

    async with db_state.session_factory() as s:
        return list((await s.execute(select(BillingOp).order_by(BillingOp.id))).scalars())


async def held_image(pipe, gauge, coll):
    """An ingested image: its original under a committed hold, as ingest leaves it."""
    img = await pipe.image(coll)
    row = await pipe.row(img)
    hold = await gauge.reserve(DEFAULT_TENANT, billing.METER, row.size_bytes, "seed", source="t")
    await gauge.commit(hold.id)
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == img)
            .values(storage_hold_id=hold.id, storage_bytes=row.size_bytes)
        )
        await s.commit()
    return img, hold.id
