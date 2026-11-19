"""FeedEvent builders for the feed tests: in-memory rows, no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sm_events.calendar import rrule
from sm_events.calendar.times import localize, to_span
from sm_events.feeds.ics_event import FeedEvent
from sm_events.models import Event, EventText, OccurrenceOverride

VIENNA = ZoneInfo("Europe/Vienna")
STAMP = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)


def make(
    *,
    start="2026-07-06T10:00",
    end="2026-07-06T11:30",
    tz="Europe/Vienna",
    all_day=False,
    rule: str | None = None,
    overrides=(),
    text: dict | None = None,
    url="https://example.org/events/concert",
    category=None,
    parent_uid=None,
    **fields,
) -> FeedEvent:
    span = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=rule is not None)
    parsed = rrule.parse(rule, all_day=all_day, timezone=tz) if rule else None
    event = Event(
        id=uuid.uuid4(),
        uid=f"{uuid.uuid4()}@simple-module-events",
        calendar_id=uuid.uuid4(),
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone=tz,
        all_day=all_day,
        rrule=parsed.text if parsed else None,
        revision=fields.pop("revision", 7),
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        updated_at=STAMP,
        status="published",
        **fields,
    )
    fields_text = {"title": "Concert", "slug": "concert", "summary": None, **(text or {})}
    return FeedEvent(
        event=event,
        text=EventText(
            event_id=event.id, locale="en", description="<p>Come along</p>", **fields_text
        ),
        overrides=tuple(overrides),
        url=url,
        category=category,
        parent_uid=parent_uid,
    )


def override(item_event: Event, kind: str, original: datetime, **kw) -> OccurrenceOverride:
    return OccurrenceOverride(event_id=item_event.id, original_start=original, kind=kind, **kw)


def series_item() -> FeedEvent:
    base = make(rule="FREQ=WEEKLY;COUNT=8", start="2026-03-16T10:00", end="2026-03-16T11:00")
    event = base.event

    def week(n: int) -> datetime:
        return localize(datetime(2026, 3, 16, 10) + timedelta(weeks=n - 1), VIENNA)

    return FeedEvent(
        event=event,
        text=base.text,
        overrides=(
            override(event, "skipped", week(5)),
            override(
                event,
                "moved",
                week(3),
                starts_at=week(3) + timedelta(hours=1),
                ends_at=week(3) + timedelta(hours=2),
            ),
            override(event, "cancelled", week(4)),
        ),
        url=base.url,
        category=None,
        parent_uid=None,
    )
