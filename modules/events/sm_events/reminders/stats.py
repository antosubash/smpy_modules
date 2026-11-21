"""The reminder counts of the last 30 days: delivered, failed by reason, unfinished.

Two readers, one function. A user sees **their own** counts (``user_id``), on their Reminders
page; a manager sees the **tenant's** (no ``user_id``) on the Delivery card, as counts only: nothing
here returns who was or was not reminded. ``unfinished`` is a claim that never reached a final state
(``claimed``, ``sending``) and is older than ``REMINDER_UNFINISHED_AFTER``: such a reminder is lost,
never retried. Every statement carries the bound tenant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from sm_events.core.constants import reminders_limits as limits
from sm_events.core.tenancy import bound_tenant
from sm_events.core.user_ids import canonical_user_id
from sm_events.models import ReminderSent

__all__ = ["Counts", "counts"]

_T = ReminderSent.__table__


@dataclass(frozen=True)
class Counts:
    sent: int
    failed: dict[str, int] = field(default_factory=dict)
    unfinished: int = 0


async def counts(
    db: Any, *, now: datetime, days: int = limits.STATS_WINDOW_DAYS, user_id: str | None = None
) -> Counts:
    since = now - timedelta(days=days)
    where: list[Any] = [_T.c.tenant_id == bound_tenant(), _T.c.claimed_at >= since]
    if user_id is not None:
        where.append(_T.c.recipient_id == canonical_user_id(user_id))  # as every row was written
    sent = (
        await db.execute(select(func.count()).select_from(_T).where(*where, _T.c.state == "sent"))
    ).scalar_one()
    failed = {
        code: int(n)
        for code, n in await db.execute(
            select(_T.c.code, func.count())
            .where(*where, _T.c.state == "failed")
            .group_by(_T.c.code)
        )
    }
    stale = now - limits.REMINDER_UNFINISHED_AFTER
    unfinished = (
        await db.execute(
            select(func.count())
            .select_from(_T)
            .where(*where, _T.c.state.in_(("claimed", "sending")), _T.c.claimed_at < stale)
        )
    ).scalar_one()
    return Counts(sent=int(sent), failed=failed, unfinished=int(unfinished))
