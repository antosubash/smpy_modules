"""Items to write: a mapped event as the parse step would stage it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sm_events.feeds.importing.model import MappedEvent, MappedOverride
from sm_events.models import EventImport, EventImportItem
from sm_events.web.schemas.events_in import TimesIn

from tests.feeds.importing.staging_support import make_import

__all__ = ["make_item", "mapped_event", "setup"]


def mapped_event(**over: Any) -> MappedEvent:
    fields: dict[str, Any] = {
        "uid": "n@x",
        "times": TimesIn(
            timezone="Europe/Vienna", start="2026-07-01T10:00", end="2026-07-01T11:00"
        ),
        "rrule": None,
        "cancelled": False,
        "attendance_mode": "in_person",
        "venue_name": None,
        "online_url": None,
        "latitude": None,
        "longitude": None,
        "category_id": None,
        "title": "Imported",
        "description": "<p>Body</p>",
        "private_class": False,
        "overrides": [],
    }
    fields.update(over)
    return MappedEvent(**fields)


def moved(original: datetime, start: str, end: str) -> MappedOverride:
    return MappedOverride(original_start=original, kind="moved", start=start, end=end)


async def make_item(
    db: Any,
    imp: EventImport,
    event: MappedEvent | None = None,
    *,
    seq: int = 1,
    verdict: str = "new",
    reason: str | None = None,
    existing: uuid.UUID | None = None,
    revision: int | None = None,
) -> EventImportItem:
    event = event or mapped_event()
    item = EventImportItem(
        import_id=imp.id,
        seq=seq,
        uid=event.uid,
        verdict=verdict,
        reason=reason,
        notes=[],
        title=event.title,
        existing_event_id=existing,
        expected_revision=revision,
        payload=event.model_dump(mode="json") if verdict != "skip" else {},
    )
    db.add(item)
    await db.flush()
    return item


async def setup(
    db: Any, calendar, *, publish=False, grants=("events.view", "events.manage"), by="m"
):
    return await make_import(db, calendar, status="running", publish=publish, grants=grants, by=by)
