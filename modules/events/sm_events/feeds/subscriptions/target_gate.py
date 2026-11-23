"""The per-server fetch spacing, enforced on the validated IP actually about to be contacted.

``admit`` is one atomic statement per request (the first and every redirect hop, each address a
fetch tries): insert the tenant's row for the server, or move its ``last_attempt_at`` forward
only when the last connection is a whole spacing ago. Whoever's statement changes a row won. A
caller that is early waits out the (few seconds) remainder and asks once more; one that still
loses is told to try later and does not connect. Within one fetch :class:`TargetGate` remembers
the servers it already admitted, so a redirect to the same server is not a second attempt. A
server is its IP address, an IPv6 one by its /64 (privacy addresses rotate inside it). Nothing
here sees or stores a URL or a name, and nothing is logged.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import finalize_session, mark_written
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant, tenant_scope
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.models import FetchTarget

__all__ = ["TargetGate", "admit", "target_key"]

_SPACING = timedelta(seconds=constants.SUBSCRIPTION_TARGET_SPACING_SECONDS)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def target_key(ip: str) -> str:
    """The server an address stands for: the address, or the /64 of an IPv6 one."""
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


async def admit(db: Any, key: str, now: datetime) -> timedelta | None:
    """``None`` when this caller may connect to ``key`` now (and the attempt is recorded); else
    how long until the last connection is a whole spacing old."""
    table = FetchTarget.__table__
    dialect = postgresql if db.sync_session.get_bind().dialect.name == "postgresql" else sqlite
    stmt = (
        dialect.insert(table)
        .values(tenant_id=bound_tenant(), ip=key, last_attempt_at=now)
        .on_conflict_do_update(
            index_elements=[table.c.tenant_id, table.c.ip],
            set_={"last_attempt_at": now},
            where=table.c.last_attempt_at <= now - _SPACING,
        )
    )
    result = await db.execute(stmt)
    mark_written(db)  # Core DML: the ORM never sees it
    if result.rowcount == 1:
        return None
    last = (
        await db.execute(
            select(table.c.last_attempt_at).where(
                table.c.tenant_id == bound_tenant(), table.c.ip == key
            )
        )
    ).scalar_one_or_none()
    return max(timedelta(0), last + _SPACING - now) if last is not None else _SPACING


class TargetGate:
    """One fetch's gate: awaited with each validated IP before the connection is made."""

    def __init__(
        self,
        factory: Any,
        tenant: str,
        utc_now: Callable[[], datetime],
    ) -> None:
        self._factory, self._tenant, self._now = factory, tenant, utc_now
        self._admitted: set[str] = set()

    async def _ask(self, key: str, now: datetime) -> timedelta | None:
        with tenant_scope(self._tenant):
            async with self._factory() as db:
                wait = await admit(db, key, now)
                await finalize_session(db)
        return wait

    async def __call__(self, ip: str) -> None:
        key = target_key(ip)
        if key in self._admitted:
            return
        now = self._now()
        wait = await self._ask(key, now)
        if wait is not None and wait <= _SPACING:  # early: wait out what remains, ask once more
            await _sleep(wait.total_seconds())
            wait = await self._ask(key, now + wait)
        if wait is not None:  # the server is busy beyond a spacing, or the slot went to another
            raise FetchFailure(
                "try_later", retry_after=constants.SUBSCRIPTION_TARGET_SPACING_SECONDS
            )
        self._admitted.add(key)
