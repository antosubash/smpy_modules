"""The database's clock, for the deadlines images hands billing.

An op's ``not_after`` is fixed from the database's time when the op is
written (plus ``BILLING_OP_MAX_AGE``), never from a worker's clock: billing
admits a call by its database's clock too (``sm_billing.metering.dbtime``), so
no worker's skew moves an op's deadline. Postgres: ``clock_timestamp()``;
SQLite: ``strftime`` in UTC. Read it after the
transaction's first write (SQLite: a transaction that reads first can fail
to write with ``SQLITE_BUSY_SNAPSHOT``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

__all__ = ["db_now"]


async def db_now(db: Any) -> datetime:
    """The database's current time: aware UTC, whole seconds (the value is
    stored on the op and passed to billing unchanged, so it must survive any
    column's round trip exactly)."""
    if db.get_bind().dialect.name == "postgresql":
        value = (await db.execute(select(func.clock_timestamp()))).scalar_one()
        value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    else:
        raw = (await db.execute(select(func.strftime("%Y-%m-%d %H:%M:%S", "now")))).scalar_one()
        value = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    return value.replace(microsecond=0)
