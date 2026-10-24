"""Metering errors that reach the client."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from sm_billing.errors import BillingError

_SQLITE_BUSY = 5  # the primary code; BUSY_SNAPSHOT (517) and the rest share it


class UsageBusyError(BillingError):
    """SQLite could not take the write lock for a metering write → 503.

    It fails closed: the call is not counted *and* not admitted. In practice
    only ``consume(db=…)`` on SQLite meets it, when the caller's transaction
    read before the metering write and another writer committed in between
    (``SQLITE_BUSY_SNAPSHOT``, which ``busy_timeout`` cannot wait out). The
    client retries after a second.
    """

    def __init__(self) -> None:
        super().__init__("usage_busy", 503)
        self.headers = {"Retry-After": "1"}


def is_sqlite_busy(exc: OperationalError) -> bool:
    """Whether ``exc`` is SQLite's "database is locked" family."""
    orig = exc.orig
    code = getattr(orig, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xFF == _SQLITE_BUSY
    return "database is locked" in str(orig)
