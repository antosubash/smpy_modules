"""Import rows and a calendar to put them in, for the staging, runner and API tests."""

from __future__ import annotations

from typing import Any

from sm_events.models import Calendar, EventImport

from tests.feeds.importing import corpus
from tests.support.access import seed_calendars

__all__ = ["make_import", "seed"]

seed = seed_calendars


async def make_import(
    db: Any,
    calendar: Calendar,
    *,
    status: str = "uploaded",
    data: bytes | None = None,
    by: str = "m",
    publish: bool = False,
    grants: tuple[str, ...] = ("events.view", "events.manage"),
    **fields: Any,
) -> EventImport:
    imp = EventImport(
        calendar_id=calendar.id,
        created_by=by,
        status=status,
        filename="x.ics",
        size_bytes=0,
        source=corpus.simple() if data is None else data,
        publish=publish,
        grants=list(grants),
        may_publish="events.publish" in grants,
        **fields,
    )
    db.add(imp)
    await db.flush()
    return imp
