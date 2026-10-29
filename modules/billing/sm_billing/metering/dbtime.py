"""The database's clock: the one time authority for key admission.

A deadline (``not_after``) is compared with the time of the database that
records the outcome, read *after* the key is claimed - never with the
caller's clock or one captured before the claim, so neither clock skew between
workers nor a call paused between its check and its write can let a late call
through.

- Postgres: ``clock_timestamp()``, the time at the statement (``now()`` is the
  transaction's start, before the claim waited on a concurrent one).
- SQLite: ``strftime('%Y-%m-%d %H:%M:%f', 'now')`` in UTC, to the millisecond,
  read once the transaction holds the writer lock (after the claim's insert).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from sm_billing.metering.periods import as_utc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_SQLITE_FORMAT = "%Y-%m-%d %H:%M:%f"


async def now(session: AsyncSession) -> datetime:
    """The database's current time (UTC, aware), in ``session``'s transaction."""
    if session.get_bind().dialect.name == "postgresql":
        value = (await session.execute(select(func.clock_timestamp()))).scalar_one()
        return as_utc(value)
    raw = (await session.execute(select(func.strftime(_SQLITE_FORMAT, "now")))).scalar_one()
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
