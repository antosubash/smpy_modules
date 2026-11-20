"""The per-server fetch floor, enforced on the validated IP actually about to be contacted.

``admit`` is one atomic statement per request (the first and every redirect hop): insert the
tenant's row for the IP, or move its ``last_attempt_at`` forward only when the last attempt is a
whole floor ago. Whoever's statement changes a row won; a loser is told to try later and does not
connect. Within one fetch :class:`TargetGate` remembers the IPs it already admitted, so a redirect
to the same server is not a second attempt. Nothing here sees or stores a URL or a name, and
nothing is logged.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import finalize_session, mark_written
from sqlalchemy.dialects import postgresql, sqlite

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant, tenant_scope
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.models import FetchTarget

__all__ = ["TargetGate", "admit"]


async def admit(db: Any, ip: str, now: datetime) -> bool:
    """``True`` when this caller may connect to ``ip`` now (and the attempt is recorded)."""
    table = FetchTarget.__table__
    dialect = postgresql if db.sync_session.get_bind().dialect.name == "postgresql" else sqlite
    floor = now - timedelta(seconds=constants.SUBSCRIPTION_HOST_FLOOR_SECONDS)
    stmt = (
        dialect.insert(table)
        .values(tenant_id=bound_tenant(), ip=ip, last_attempt_at=now)
        .on_conflict_do_update(
            index_elements=[table.c.tenant_id, table.c.ip],
            set_={"last_attempt_at": now},
            where=table.c.last_attempt_at <= floor,
        )
    )
    result = await db.execute(stmt)
    mark_written(db)  # Core DML: the ORM never sees it
    return result.rowcount == 1


class TargetGate:
    """One fetch's gate: awaited with each validated IP before the connection is made."""

    def __init__(self, factory: Any, tenant: str, utc_now: Callable[[], datetime]) -> None:
        self._factory, self._tenant, self._now = factory, tenant, utc_now
        self._admitted: set[str] = set()

    async def __call__(self, ip: str) -> None:
        if ip in self._admitted:
            return
        with tenant_scope(self._tenant):
            async with self._factory() as db:
                won = await admit(db, ip, self._now())
                await finalize_session(db)
        if not won:  # not a failure of the feed: it is rescheduled after the floor
            raise FetchFailure("try_later", retry_after=constants.SUBSCRIPTION_HOST_FLOOR_SECONDS)
        self._admitted.add(ip)
