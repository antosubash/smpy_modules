"""The preview's verdict for each mapped item: new, update (with the revision seen) or skip.

One query per chunk of UIDs reads the calendar's events **with the trash**, because the unique key
``(tenant, calendar, uid)`` spans it: a UID held by a trashed event is ``uid_in_trash`` (the
import does not resurrect what a person deleted), a live one is an ``update`` that remembers the
revision it saw (``expected_revision``, which the apply step's stale guard compares), and a UID
only in another calendar is a new event here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.importing.mapper import MappedItem
from sm_events.models import Event, EventImport, EventImportItem

__all__ = ["existing_uids", "item_row"]


async def existing_uids(
    db: Any, calendar_id: uuid.UUID, uids: Sequence[str]
) -> dict[str, tuple[uuid.UUID, int, bool]]:
    """``{uid: (event id, revision, trashed)}`` for the calendar's events, trash included."""
    found: dict[str, tuple[uuid.UUID, int, bool]] = {}
    for start in range(0, len(uids), constants.IMPORT_UID_CHUNK):
        chunk = list(uids[start : start + constants.IMPORT_UID_CHUNK])
        stmt = (
            select(Event.id, Event.uid, Event.revision, Event.is_deleted)
            .where(
                Event.tenant_id == bound_tenant(),  # type: ignore[arg-type]
                Event.calendar_id == calendar_id,  # type: ignore[arg-type]
                Event.uid.in_(chunk),  # type: ignore[attr-defined]
            )
            .execution_options(include_deleted=True)
        )
        for row in await db.execute(stmt):
            found[row.uid] = (row.id, row.revision, bool(row.is_deleted))
    return found


def item_row(
    imp: EventImport, seq: int, item: MappedItem, existing: dict[str, tuple[uuid.UUID, int, bool]]
) -> EventImportItem:
    verdict, reason, event_id, revision = "skip", item.skip, None, None
    if item.event is not None:
        held = existing.get(item.uid)
        if held is None:
            verdict, reason = "new", None
        elif held[2]:
            reason = "uid_in_trash"
        else:
            verdict, reason, event_id, revision = "update", None, held[0], held[1]
    return EventImportItem(
        import_id=imp.id,
        seq=seq,
        uid=item.uid[: constants.UID_MAX],
        verdict=verdict,
        reason=reason,
        notes=list(item.notes),
        title=item.title,
        starts_at=item.starts_at if verdict != "skip" else None,
        all_day=item.all_day,
        recurring=item.recurring,
        existing_event_id=event_id,
        expected_revision=revision,
        payload=item.event.model_dump(mode="json") if verdict != "skip" and item.event else {},
    )
