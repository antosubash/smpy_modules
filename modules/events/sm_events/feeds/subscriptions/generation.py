"""The one place a subscription's policy generation moves.

Stored items must always belong to the subscription's current (address, policy): they were
fetched under one address, one ``public`` and one ``may_use_private``, and any of them changing
means they may have come from somewhere the new policy would not allow. ``restart`` is the only
code that assigns ``policy_generation`` (a test scans the package for any other); it also
deletes the items, resets the validators and makes the subscription due through the one "may a
fetch start" decision. Every read additionally requires ``items_generation ==
policy_generation``, so a path that somehow kept rows still shows none of them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete as sa_delete

from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import rules
from sm_events.models import ExternalItem, Subscription

__all__ = ["restart"]


async def restart(db: Any, sub: Subscription, now: datetime) -> None:
    """Start a new generation: forget the items, the validators and the failure state, and make
    the subscription due again. An in-flight fetch is fenced out by the counter (its store sees
    another generation) and no lease is cleared."""
    sub.policy_generation += 1
    items = ExternalItem.__table__
    await db.execute(
        sa_delete(items).where(
            items.c.tenant_id == bound_tenant(), items.c.subscription_id == sub.id
        )
    )
    mark_written(db)  # Core DML: the ORM never sees it
    sub.item_count, sub.last_counts = 0, {}
    sub.etag = sub.last_modified = None
    rules.make_due(sub, now)
