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
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


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


@runtime_checkable
class UsageMeter(Protocol):
    """Race-safe, idempotent per-period counters, keyed by tenant and meter.

    Every write runs in its own short transaction unless ``db=`` is passed
    (see ``consume``). A replayed ``idempotency_key`` is never counted twice:
    it returns the original outcome with ``replayed=True``.
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
    ) -> Allowed | Exceeded:
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
    ) -> Allowed:
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


__all__ = ["Allowed", "Exceeded", "UsageMeter"]
