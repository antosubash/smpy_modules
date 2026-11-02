"""A stand-in for billing's ``UsageMeter`` on the storage gauge.

``conftest`` turns billing off for every test (no billing tables here): the
seam then answers as on a host without billing. ``gauge`` installs this fake
instead - the hold calls (``sm_images.core.billing.storage_meter``) and the web
pre-flight (``app.state.billing_usage``) - so a test can set a limit, read
what is held, and make billing fail (``fail_swap``, ``fail_release``).

Its ``swap`` is billing's: one atomic step (no ``await`` between the check
and the write), the limit on the net delta, a replayed key returning the
same hold, a closed key (``close_key``) answering ``Closed`` to any call.
Keys and holds are scoped to their subject, as billing's: a key used under
another subject is another key (``close_key`` there answers ``Closed`` and
leaves the real one open), and ``get_hold`` answers ``None`` for another
subject's hold - so a call under the wrong subject shows in the outcome.
:func:`assert_counted_once` is the invariant every test ends on.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sm_billing.contracts.metering import (
    Allowed,
    Closed,
    Exceeded,
    Expired,
    Hold,
    HoldNotFound,
    IdempotencyConflict,
    Refused,
)
from sm_images.core import billing
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import BillingOp, Image
from sqlalchemy import select, update

LIVE = ("held", "committed")


@dataclass
class FakeGauge:
    limit: int | None = None
    holds: dict[str, Hold] = field(default_factory=dict)
    keys: dict[str, Any] = field(default_factory=dict)
    """Each key's outcome: its hold id, or the ``Exceeded``/``Expired``/``Closed``."""
    calls_by_key: dict[str, tuple] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    limits: dict[str, int] = field(default_factory=dict)
    """Per-subject limits overriding ``limit`` (the gauge counts per subject)."""
    key_subject: dict[str, str] = field(default_factory=dict)
    """The subject each key was first used under (its namespace)."""
    fail_swap: int = 0
    """The next N swaps raise (billing unreachable)."""
    fail_release: int = 0
    fail_close: int = 0
    delay: float = 0.0
    """Seconds a swap takes before billing decides: concurrent swaps interleave."""
    later: timedelta = timedelta(0)
    """How far billing's clock runs ahead of real time (days passing)."""

    def forget(self, key: str) -> None:
        """Billing's retention purged the key's settled outcome."""
        self.keys.pop(key, None)
        self.calls_by_key.pop(key, None)
        self.key_subject.pop(key, None)

    def _ns(self, subject: str, key: str) -> str:
        """The key's slot in ``keys``: billing keys a key by ``(subject, key)``,
        so one used under another subject than its first is a different key."""
        owner = self.key_subject.setdefault(key, subject)
        return key if owner == subject else f"{subject}|{key}"

    @property
    def level(self) -> int:
        return sum(h.quantity for h in self.holds.values() if h.status in LIVE)

    def level_of(self, subject: str) -> int:
        """Bytes live holds count for ``subject``."""
        return sum(
            h.quantity for h in self.holds.values() if h.status in LIVE and h.tenant_id == subject
        )

    def limit_of(self, subject: str) -> int | None:
        return self.limits.get(subject, self.limit)

    def live(self, status: str | None = None) -> list[Hold]:
        want = (status,) if status else LIVE
        return [h for h in self.holds.values() if h.status in want]

    def _set(self, hold: Hold, status: str) -> Hold:
        new = Hold(hold.id, hold.tenant_id, hold.meter, hold.quantity, status, None)
        self.holds[hold.id] = new
        return new

    async def check(self, tenant_id: str, meter: str, qty: int = 1):
        self.calls.append(("check", tenant_id, meter, str(qty)))
        level, limit = self.level_of(tenant_id), self.limit_of(tenant_id)
        if limit is not None and level + qty > limit:
            return Exceeded(level, limit, qty, None)
        return Allowed(level, limit, None)

    async def swap(
        self, tenant_id, meter, old_hold_id, quantity, idempotency_key, *, source, not_after=None
    ):
        self.calls.append(("swap", str(old_hold_id), str(quantity), idempotency_key, tenant_id))
        idempotency_key = self._ns(tenant_id, idempotency_key)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_swap:
            self.fail_swap -= 1
            raise RuntimeError("billing is down")
        call = (old_hold_id, quantity, source, not_after)
        if isinstance(self.keys.get(idempotency_key), Closed):  # key-wide: any call
            return self.keys[idempotency_key]
        if idempotency_key in self.keys:  # a replay: the key's outcome, for the same call
            outcome, first = self.keys[idempotency_key], self.calls_by_key[idempotency_key]
            if first != call:
                raise IdempotencyConflict(idempotency_key)
            return outcome if not isinstance(outcome, str) else self.holds[outcome]
        old = self.holds.get(old_hold_id) if old_hold_id else None
        if old is not None and old.tenant_id != tenant_id:
            raise HoldNotFound(old_hold_id)
        self.calls_by_key[idempotency_key] = call
        late = not_after is not None and datetime.now(UTC) + self.later > not_after
        if late:  # billing enforces the deadline (``None``: a test seeding, no deadline)
            self.keys[idempotency_key] = Expired(idempotency_key, not_after)
            return self.keys[idempotency_key]
        freed = old.quantity if old is not None and old.status in LIVE else 0
        level, limit = self.level_of(tenant_id), self.limit_of(tenant_id)
        grows = quantity > freed and limit is not None
        if grows and level - freed + quantity > limit:
            refused = Exceeded(level, limit, quantity - freed, None)
            self.keys[idempotency_key] = refused  # the refusal is the key's outcome
            return refused
        if freed:
            self._set(old, "released")
        hold = Hold(uuid.uuid4().hex, tenant_id, meter, quantity, "committed", None)
        self.holds[hold.id] = hold
        self.keys[idempotency_key] = hold.id
        return hold

    async def close_key(self, tenant_id: str, meter: str, key: str):
        """The key's outcome, or ``Closed`` committed now (billing's ``close_key``)."""
        self.calls.append(("close_key", tenant_id, key))
        if self.fail_close:
            self.fail_close -= 1
            raise RuntimeError("billing is down")
        key = self._ns(tenant_id, key)
        outcome = self.keys.setdefault(key, Closed(key))
        if isinstance(outcome, str):
            return self.holds[outcome]
        return Refused(key) if isinstance(outcome, Exceeded) else outcome

    async def get_hold(self, tenant_id: str, hold_id: str) -> Hold | None:
        self.calls.append(("get_hold", tenant_id, hold_id))
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


@pytest.fixture
def user_mode(monkeypatch):
    """Billing's ``user`` subject mode: every owner exists. Returns a setter that
    puts a ``Runtime`` (``user_mode.runtime(rt)``) or an app
    (``user_mode.app(app)``) in the mode."""
    from sm_images.core.billing import subject

    async def exists(db, who):
        return True

    monkeypatch.setattr(subject, "user_exists", exists)

    def runtime(rt):
        return dataclasses.replace(rt, subject_mode=lambda: "user")

    def app(app):
        app.state.billing_subject_mode = "user"
        return app

    def web(app_=None):
        """The web path: ``subject.runtime_mode()`` (ingest, ``slots``) reads user."""
        monkeypatch.setattr(subject, "runtime_mode", lambda: subject.USER)
        return user_mode_ns if app_ is None else app(app_)

    user_mode_ns = SimpleNamespace(runtime=runtime, app=app, web=web)
    return user_mode_ns


async def no_settle(*args, **kwargs) -> int:
    """Stands in for ``billing_ops.settle``: the test settles when it chooses."""
    return 0


async def ops(db_state) -> list:
    """Every outbox row, oldest first."""
    async with db_state.session_factory() as s:
        return list((await s.execute(select(BillingOp).order_by(BillingOp.id))).scalars())


async def held_image(pipe, gauge, coll, subject: str = DEFAULT_TENANT):
    """An ingested image: its original under a committed hold, as ingest leaves
    it - under ``subject``, recorded on the image when it is not the tenant."""
    img = await pipe.image(coll)
    row = await pipe.row(img)
    hold = await gauge.swap(subject, billing.METER, None, row.size_bytes, "seed", source="t")
    recorded = None if subject == DEFAULT_TENANT else subject
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == img)
            .values(storage_hold_id=hold.id, storage_bytes=row.size_bytes, storage_subject=recorded)
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
