"""What the counter and hold halves of ``UsageService`` share: the session
factory, the clock, the meter registry and the read side (limit and period).

Reads run in a short session of their own, closed before any write starts
(see ``service``'s docstring for why the order matters on SQLite).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sm_billing.metering.periods import current_period
from sm_billing.resolve import effective_plan

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sm_billing.contracts.metering import MeterDefinition, MeterKind
    from sm_billing.metering.registry import MeterRegistry

#: The hold TTL when neither the caller, the meter nor a setting gives one.
DEFAULT_HOLD_TTL = 900


@dataclass(frozen=True)
class Resolved:
    limit: int | None
    period: tuple[datetime, datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MeteringCore:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        clock: Callable[[], datetime] = _utcnow,
        meters: MeterRegistry | None = None,
        hold_ttl: Callable[[], int] | None = None,
    ) -> None:
        """``meters`` ``None`` accepts any key (unit tests of the primitives);
        billing always passes ``app.state.billing_meters``. ``hold_ttl`` reads
        the ``usage_hold_ttl_seconds`` setting per call."""
        self._factory = session_factory
        self._clock = clock
        self._meters = meters
        self._hold_ttl = hold_ttl

    @property
    def session_factory(self) -> async_sessionmaker:
        return self._factory

    def now(self) -> datetime:
        return self._clock()

    def _require(self, meter: str, kind: MeterKind) -> MeterDefinition | None:
        """``UnknownMeterError`` unless ``meter`` is a registered ``kind`` meter."""
        return None if self._meters is None else self._meters.require(meter, kind)

    def _default_ttl(self, definition: MeterDefinition | None) -> int:
        if definition is not None and definition.hold_ttl_seconds is not None:
            return definition.hold_ttl_seconds
        return self._hold_ttl() if self._hold_ttl is not None else DEFAULT_HOLD_TTL

    @asynccontextmanager
    async def _reader(self, db: AsyncSession | None):
        """The caller's session when joined, else a short one of our own."""
        if db is not None:
            yield db
            return
        async with self._factory() as session:
            yield session

    async def _resolve(self, tenant_id: str, meter: str, db: AsyncSession | None) -> Resolved:
        now = self._clock()
        async with self._reader(db) as session:
            plan, sub = await effective_plan(session, tenant_id)
            period = current_period(sub, now)
        value = plan.limits.get(meter)
        return Resolved(None if value is None else int(value), period)
