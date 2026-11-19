"""One batch of an import: each item written in a savepoint of its own (Ruling 28).

The batch is one transaction (the caller's): the item writes, each item's outcome and the
fenced counter update, so a crash or a lost lease rolls all of it back and the next claim redoes
exactly those items (their ``outcome`` is still ``NULL``). Inside it an item is isolated: a
refusal is a ``skipped`` outcome with its code (``write_item`` decides), and any other
exception, an ``IntegrityError`` included, is ``failed`` / ``write_failed``, logged by class
name only (the message can carry a value from the file), while its neighbours are written.

The items and the import are detached from the session first: a rolled-back savepoint expires
every attached object, and an expired attribute cannot be read in an async session. Outcomes
are written with ``UPDATE`` statements by id instead.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import update

from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.importing.write import write_item
from sm_events.models import EventImport, EventImportItem

__all__ = ["BatchResult", "apply_batch"]

logger = logging.getLogger(__name__)
_COUNTERS = {
    "created": "created",
    "updated": "updated",
    "unchanged": "unchanged",
    "skipped": "skipped",
    "failed": "failed",
}


@dataclass
class BatchResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    processed: int = 0

    def count(self, outcome: str) -> None:
        setattr(self, _COUNTERS[outcome], getattr(self, _COUNTERS[outcome]) + 1)
        self.processed += 1


async def apply_batch(
    db: Any,
    imp: EventImport,
    items: Sequence[EventImportItem],
    *,
    locales: tuple[str, ...],
    now: datetime,
) -> BatchResult:
    """Write ``items`` (those with no outcome yet) and record each outcome; no commit."""
    table = EventImportItem.__table__
    tenant = bound_tenant()
    db.expunge(imp)
    for item in items:
        db.expunge(item)
    result = BatchResult()
    for item in items:
        event_id, code = None, None
        try:
            async with db.begin_nested():
                written = await write_item(db, imp, item, locales=locales, now=now)
        except Exception as exc:  # the class only: its message can quote the file
            logger.warning(
                "events: import %s item %s failed (%s)", imp.id, item.seq, type(exc).__name__
            )
            outcome, code = "failed", "write_failed"
        else:
            outcome, code, event_id = written.outcome, written.code, written.event_id
        await db.execute(
            update(table)
            .where(table.c.id == item.id, table.c.tenant_id == tenant)
            .values(outcome=outcome, outcome_code=code, event_id=event_id)
            .execution_options(synchronize_session=False)
        )
        result.count(outcome)
    return result
