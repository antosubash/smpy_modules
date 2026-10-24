"""The usage-metering seam: what a consumer module calls to count usage.

Billing installs an implementation as ``app.state.billing_usage``. A consumer
reads it per request — ``getattr(request.app.state, "billing_usage", None)``
— and treats ``None`` as "billing is not installed, so nothing is limited".
It imports these types only under ``TYPE_CHECKING``, so it never depends on
the billing package at runtime, the way ``tenants``' ``EntitlementProvider``
lets consumers ask about limits without importing billing.

The protocol lives here for now. Upstream issue
antosubash/simple_module_python#616 tracks moving it next to
``EntitlementProvider`` in ``tenants.contracts`` so consumers can type against
the framework instead; until then this module is the contract.

Meter keys are ``Plan.limits`` keys (``"ai.requests"``): an absent key is
unlimited and ``0`` forbids, exactly as for ``tenants.seats``. Quantities are
integers in the meter's minor unit (tokens, bytes, ms). Never put personal data
in an idempotency key or ``source``: use request or job ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession


class MeterKind(StrEnum):
    """A counter resets every billing period; a gauge is a level held by holds."""

    COUNTER = "counter"
    GAUGE = "gauge"


@dataclass(frozen=True)
class MeterDefinition:
    """A meter a consumer registered on ``app.state.billing_meters``.

    ``key`` is the ``Plan.limits`` key. ``label_key`` is an i18n key in the
    *consumer's* catalogue. ``hold_ttl_seconds`` (gauges) is the default TTL of
    a hold on this meter; without it the ``usage_hold_ttl_seconds`` setting.
    """

    key: str
    kind: MeterKind
    unit: str = "count"
    label_key: str = ""
    hold_ttl_seconds: int | None = None


class HoldStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


#: The statuses whose quantity counts toward the gauge.
LIVE_HOLD_STATUSES = frozenset({HoldStatus.HELD, HoldStatus.COMMITTED})


@dataclass(frozen=True)
class Allowed:
    """The call counted (or was a replay of one that did).

    ``used`` is the period's total after the call, ``limit`` ``None`` when the
    plan sets none, and ``period_end`` when the counter resets.
    """

    used: int
    limit: int | None
    period_end: datetime | None
    replayed: bool = False

    #: ``outcome.ok`` tells the two apart without importing either class.
    ok: ClassVar[bool] = True


@dataclass(frozen=True)
class Exceeded:
    """Refused: ``used + requested`` would pass ``limit``. Nothing was written."""

    used: int
    limit: int
    requested: int
    period_end: datetime | None

    ok: ClassVar[bool] = False


@dataclass(frozen=True)
class Refunded:
    """A replay of a key whose call was since refunded: **not** admitted.

    The key is spent; a retry that should count again needs a new key.
    """

    used: int
    limit: int | None
    period_end: datetime | None
    replayed: bool = True

    ok: ClassVar[bool] = False


@dataclass(frozen=True)
class Hold:
    """A reservation against a gauge; ``id`` is the handle for the calls after.

    ``ok`` is whether it still counts (``held`` or ``committed``): a replayed
    key whose hold was since released or expired comes back not ``ok``.
    """

    id: str
    tenant_id: str
    meter: str
    quantity: int
    status: str
    expires_at: datetime | None
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.status in LIVE_HOLD_STATUSES


class UnknownMeterError(LookupError):
    """The meter is not registered (or is the other kind): a programming error."""


class HoldNotFound(LookupError):  # noqa: N818 - reads as the condition
    """No hold has this id. Billing maps it to 404 ``hold_not_found``."""


class HoldExpired(Exception):  # noqa: N818 - reads as the condition
    """The hold no longer counts (``status``: expired or released), so it
    cannot be committed or extended. Billing maps it to 409 ``hold_expired``."""

    def __init__(self, hold_id: str, status: str) -> None:
        super().__init__(f"hold {hold_id} is {status}")
        self.hold_id = hold_id
        self.status = status


class QuotaExceededError(Exception):
    """Raised where an outcome cannot be returned (``holding``, ``RequiresQuota``).

    Billing maps it to 402 ``quota_exceeded`` with the meter, limit, used,
    requested and (counters) ``resets_at``.
    """

    def __init__(self, meter: str, outcome: Exceeded) -> None:
        super().__init__(f"{meter}: {outcome.used} + {outcome.requested} > {outcome.limit}")
        self.meter = meter
        self.outcome = outcome


class IdempotencyConflict(Exception):  # noqa: N818 - reads as the condition
    """The key was first used for a different call (quantity, kind or source).

    A key answers only for the call it was first used with, so a reused key
    can never buy an admission it did not pay for. Billing maps it to 409
    ``idempotency_conflict``.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"idempotency key {key!r} was used for a different call")
        self.key = key


@runtime_checkable
class UsageMeter(Protocol):
    """Race-safe, idempotent per-period counters, keyed by tenant and meter.

    Every write runs in its own short transaction unless ``db=`` is passed
    (see ``consume``). A replayed ``idempotency_key`` is never counted twice:
    it returns the original outcome with ``replayed=True`` — ``Refunded`` if
    that call was refunded since — and only for the same call: a key reused
    with another quantity, kind or source raises ``IdempotencyConflict``.
    """

    async def check(self, tenant_id: str, meter: str, qty: int = 1) -> Allowed | Exceeded:
        """Would ``qty`` fit right now? Advisory and read-only: a UI hint, never
        enforcement, since another call can consume between this and yours."""
        ...

    async def consume(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        db: AsyncSession | None = None,
    ) -> Allowed | Exceeded | Refunded:
        """Atomically check and count ``qty`` against the current period.

        ``db=`` joins the caller's transaction (inside a savepoint) so the
        usage commits or rolls back with the caller's own write. The counter's
        row lock is then held until the caller commits, which serialises every
        other call for that tenant and meter behind it: pass ``db=`` only when
        the rest of that transaction is short.
        """
        ...

    async def record(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        occurred_at: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> Allowed | Refunded:
        """Count usage reported after the fact, unconditionally.

        It may take the period past its limit; the next ``consume`` is then
        refused. It counts against the period current when it is recorded;
        ``occurred_at`` is kept on the ledger row for reference.
        """
        ...

    async def refund(self, tenant_id: str, meter: str, idempotency_key: str) -> bool:
        """Reverse the call made under ``idempotency_key``, in the period it
        counted against. ``False`` when there is nothing (left) to reverse."""
        ...

    async def reserve(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        ttl: int | None = None,
    ) -> Hold | Exceeded:
        """Hold ``qty`` of a gauge, atomically within its limit, for ``ttl``
        seconds (default: the meter's, else the setting). Always its own
        transaction: the hold must be visible to other requests at once."""
        ...

    async def commit(self, hold_id: str) -> Hold:
        """Keep the hold with no expiry (counted until released). Idempotent;
        ``HoldExpired`` once it expired or was released."""
        ...

    async def release(self, hold_id: str) -> bool:
        """Return the capacity. ``False`` if it was settled already."""
        ...

    async def extend(self, hold_id: str, ttl: int) -> Hold:
        """Push a held hold's expiry to ``ttl`` seconds from now (a heartbeat)."""
        ...

    def holding(
        self,
        tenant_id: str,
        meter: str,
        qty: int,
        idempotency_key: str,
        *,
        source: str,
        ttl: int | None = None,
    ) -> AbstractAsyncContextManager[Hold]:
        """``reserve`` on entry (``QuotaExceededError`` when refused) and
        ``release`` on exit, raised or not."""
        ...


__all__ = [
    "Allowed",
    "Exceeded",
    "Hold",
    "HoldExpired",
    "HoldNotFound",
    "HoldStatus",
    "IdempotencyConflict",
    "MeterDefinition",
    "MeterKind",
    "QuotaExceededError",
    "Refunded",
    "UnknownMeterError",
    "UsageMeter",
]
