"""Storing a fetched feed: the one bounded scanner, mapped in memory, then one swap.

**Scan and map first, write after.** The body goes only through PR 5's scanner and mapper (no
calendar library, no second parser), with their limits and their codes; everything is mapped in
memory before the first write, so a body that fails a bound, cannot be parsed or breaks while
mapping writes nothing. A failure raises :class:`FetchFailure` (or the original exception) and
the previous items stay exactly as they were.

**Then one swap, in a savepoint.** Items are upserted by ``(tenant, subscription, uid)`` (an
unchanged item only has ``seen_generation`` bumped: nothing else is rewritten), the subscription's
``generation`` goes up by one, and items of an older generation are deleted: pruning happens only
here, after a body that was scanned, parsed and mapped in full. The caller commits (or rolls
back) the transaction; a savepoint makes a failure inside the swap leave nothing half done.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete, func, select, update

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import ImportFailure
from sm_events.feeds.importing.mapper import map_calendar
from sm_events.feeds.importing.scan import scan
from sm_events.feeds.importing.values import ItemSkip
from sm_events.feeds.subscriptions import items
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.models import ExternalItem, Subscription

__all__ = ["StoreCounts", "store_feed"]


@dataclass(frozen=True)
class StoreCounts:
    stored: int
    skipped: int
    reasons: dict[str, int]


def _chunks[T](seq: Sequence[T]) -> Iterator[Sequence[T]]:
    for start in range(0, len(seq), constants.SUBSCRIPTION_STORE_CHUNK):
        yield seq[start : start + constants.SUBSCRIPTION_STORE_CHUNK]


def _map(body: bytes, calendar_tz: str) -> tuple[list[items.ItemValues], Counter[str]]:
    try:
        deadline = time.monotonic() + constants.IMPORT_PARSE_SECONDS
        mapped = map_calendar(
            scan(body).events, calendar_tz=calendar_tz, categories={}, deadline=deadline
        )
    except ImportFailure as failure:
        code = failure.code if failure.code in constants.SCAN_FAILURE_CODES else "ics_invalid"
        raise FetchFailure(code) from None
    values: list[items.ItemValues] = []
    reasons: Counter[str] = Counter()
    for item in mapped.items:
        if item.event is None:
            reasons[item.skip or "skipped"] += 1
            continue
        try:
            values.append(items.to_values(item.event))
        except ItemSkip as skip:
            reasons[skip.code] += 1
    return values, reasons


async def _check_caps(db: Any, sub: Subscription, count: int) -> None:
    if count > constants.SUBSCRIPTION_ITEMS_MAX:
        raise FetchFailure("too_many_events")
    table = ExternalItem.__table__
    others = (
        await db.execute(
            select(func.count())
            .select_from(table)
            .where(table.c.tenant_id == sub.tenant_id, table.c.subscription_id != sub.id)
        )
    ).scalar_one()
    if others + count > constants.SUBSCRIPTION_TENANT_ITEMS_MAX:
        raise FetchFailure("too_many_events")


async def _swap(
    db: Any, sub: Subscription, values: list[items.ItemValues], generation: int, now: datetime
) -> None:
    table = ExternalItem.__table__
    scope = (table.c.tenant_id == sub.tenant_id, table.c.subscription_id == sub.id)
    held = {
        uid: (row_id, digest)
        for uid, row_id, digest in (
            await db.execute(select(table.c.uid, table.c.id, table.c.content_hash).where(*scope))
        ).all()
    }
    fresh: list[ExternalItem] = []
    unchanged: list[int] = []
    for value in values:
        known = held.get(value.uid)
        if known is None:
            fresh.append(
                ExternalItem(
                    subscription_id=sub.id,
                    seen_generation=generation,
                    updated_at=now,
                    **value.columns(),
                )
            )
        elif known[1] == value.content_hash:
            unchanged.append(known[0])
        else:
            await db.execute(
                update(table)
                .where(table.c.id == known[0], *scope)
                .values(**value.columns(), seen_generation=generation, updated_at=now)
            )
    for chunk in _chunks(fresh):
        db.add_all(chunk)
        await db.flush()
    for ids in _chunks(unchanged):
        await db.execute(
            update(table).where(table.c.id.in_(ids), *scope).values(seen_generation=generation)
        )
    await db.execute(delete(table).where(*scope, table.c.seen_generation < generation))
    mark_written(db)  # Core DML: the ORM never sees it


async def store_feed(
    db: Any, sub: Subscription, *, calendar_tz: str, body: bytes, now: datetime | None = None
) -> StoreCounts:
    """Replace ``sub``'s items with the feed in ``body``. No commit."""
    values, reasons = _map(body, calendar_tz)
    await _check_caps(db, sub, len(values))
    generation = sub.generation + 1
    async with db.begin_nested():
        await _swap(db, sub, values, generation, now or utcnow())
    counts = StoreCounts(len(values), sum(reasons.values()), dict(reasons))
    sub.generation = generation
    sub.item_count = counts.stored
    sub.last_counts = {
        "stored": counts.stored,
        "skipped": counts.skipped,
        "reasons": counts.reasons,
    }
    await db.flush()
    return counts
