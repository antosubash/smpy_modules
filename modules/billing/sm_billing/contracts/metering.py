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
from typing import TYPE_CHECKING, Protocol, runtime_checkable

# The exceptions live in ``metering_errors`` (split for size); they are part of
# this contract, so import them from here.
from sm_billing.contracts.metering_errors import (
    HoldExpired,
    HoldNotFound,
    IdempotencyConflict,
    QuotaExceededError,
    UnknownMeterError,
)

# The result types live in ``metering_results`` (split for size); they are
# part of this contract, so import them from here.
from sm_billing.contracts.metering_results import (
    LIVE_HOLD_STATUSES,
    Allowed,
    Exceeded,
    Hold,
    HoldStatus,
    Refunded,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
        enforcement, since another call can consume between this and yours.
        A registered gauge compares its level held (``period_end`` ``None``)."""
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

    async def get_hold(self, tenant_id: str, hold_id: str) -> Hold | None:
        """The hold's current state, read-only; ``None`` for an unknown id or
        one reserved for another tenant than ``tenant_id``. A
        ``held`` hold past its ``expires_at`` is reported ``expired`` (the
        sweeper may not have settled it yet; a ``commit`` would refuse it)."""
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
        """``reserve`` on entry (``QuotaExceededError`` when refused; a replayed
        key: 409 ``idempotency_replay``) and ``release`` on exit, raised or not."""
        ...


def usage_meter(session_factory: async_sessionmaker) -> UsageMeter:
    """Billing's ``UsageMeter`` over ``session_factory``, for code with no app.

    A Celery worker never builds the app, so ``app.state.billing_usage`` is not
    there to read. This builds the same service over a factory the caller owns
    (the worker's engine): every write is still its own short transaction,
    finished with ``finalize_session``. It knows no meter registry: it takes
    any key (pass only meters registered in the web process, e.g.
    ``ai.requests``, ``images.storage_bytes``), its ``check`` is a counter's,
    and a hold without ``ttl`` gets the default TTL. Importing it imports
    billing; a consumer that treats billing as optional checks ``find_spec``.
    """
    from sm_billing.metering.service import UsageService

    return UsageService(session_factory)


__all__ = [
    "LIVE_HOLD_STATUSES",
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
    "usage_meter",
]
