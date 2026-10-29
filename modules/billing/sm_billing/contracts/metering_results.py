"""The result types of the usage-metering contract (``Allowed``, ``Exceeded``,
``Refunded``, ``Hold``) - split from ``metering`` for size. Import them from
``sm_billing.contracts.metering``, which re-exports them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar


class HoldStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"
    #: A ``swap`` the limit refused: its key's outcome, kept so a replay is refused too.
    REFUSED = "refused"


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
