"""Metering errors that reach the client."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from sm_billing.errors import BillingError

_SQLITE_BUSY = 5  # the primary code; BUSY_SNAPSHOT (517) and the rest share it


class UsageBusyError(BillingError):
    """SQLite could not take the write lock for a metering write → 503.

    It fails closed: the call is not counted *and* not admitted.
    ``tx.run_write`` maps SQLite busy for every metering write it wraps
    (consume, record, refund, adjust, holds, recount). It is most likely with
    ``consume(db=…)`` or ``record(db=…)``, when the caller's transaction read
    before the metering write and another writer committed in between
    (``SQLITE_BUSY_SNAPSHOT``, which ``busy_timeout`` cannot wait out), but an
    own-transaction write under heavy contention can also run out of
    ``busy_timeout``. The client retries after a second.
    """

    def __init__(self) -> None:
        super().__init__("usage_busy", 503)
        self.headers = {"Retry-After": "1"}


class IdempotencyReplay(BillingError):  # noqa: N818 - reads as the condition
    """A key whose charge (or hold) already went through was used again → 409.

    ``RequiresQuota`` and ``holding()`` never run the work twice for one
    charge: one key per operation. The replay itself is never counted; the
    first response is not stored, so the client treats 409
    ``idempotency_replay`` as "already done".
    """

    def __init__(self) -> None:
        super().__init__("idempotency_replay", 409)


def is_sqlite_busy(exc: OperationalError) -> bool:
    """Whether ``exc`` is SQLite's "database is locked" family."""
    orig = exc.orig
    code = getattr(orig, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xFF == _SQLITE_BUSY
    return "database is locked" in str(orig)
