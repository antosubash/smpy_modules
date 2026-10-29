"""A stand-in for billing's ``UsageMeter`` on the storage gauge.

``conftest`` turns billing off for every test (no billing tables here): the
seam then answers as on a host without billing. ``gauge`` installs this fake
instead - the hold calls (``sm_images.billing.storage_meter``) and the web
pre-flight (``app.state.billing_usage``) - so a test can set a limit and read
what is held.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest
from sm_billing.contracts.metering import Allowed, Exceeded, Hold, HoldExpired

LIVE = ("held", "committed")


@dataclass
class FakeGauge:
    limit: int | None = None
    holds: dict[str, Hold] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

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

    async def reserve(self, tenant_id, meter, qty, idempotency_key, *, source, ttl=None):
        self.calls.append(("reserve", meter, str(qty), idempotency_key))
        if idempotency_key in self.keys:
            return self.holds[self.keys[idempotency_key]]
        if self.limit is not None and self.level + qty > self.limit:
            return Exceeded(self.level, self.limit, qty, None)
        hold = Hold(uuid.uuid4().hex, tenant_id, meter, qty, "held", None)
        self.holds[hold.id] = hold
        self.keys[idempotency_key] = hold.id
        return hold

    async def commit(self, hold_id: str) -> Hold:
        self.calls.append(("commit", hold_id))
        hold = self.holds[hold_id]
        if hold.status not in LIVE:
            raise HoldExpired(hold_id)
        return self._set(hold, "committed")

    async def release(self, hold_id: str) -> bool:
        self.calls.append(("release", hold_id))
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
    return fake
