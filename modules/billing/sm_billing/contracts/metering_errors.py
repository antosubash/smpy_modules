"""The exceptions of the usage-metering contract (``sm_billing.contracts.metering``).

Split out of it for size; that module re-exports every one, and consumers
import them from there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sm_billing.contracts.metering import Exceeded

__all__ = [
    "HoldExpired",
    "HoldNotFound",
    "IdempotencyConflict",
    "QuotaExceededError",
    "UnknownMeterError",
]


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
