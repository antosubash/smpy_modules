"""The cast the registration tests share: a public calendar and builtin-registration events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sm_events.models import Calendar, Event, OccurrenceOverride, RegistrationCount
from sm_events.models.enums import Visibility

from tests.support.calendars import seed_event, seed_series
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

NOW = datetime(2026, 7, 1, 6, tzinfo=UTC)
START = datetime(2026, 7, 1, 8, tzinfo=UTC)  # 10:00 in Vienna (CEST)
WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
SECOND = datetime(2026, 7, 8, 8, tzinfo=UTC)
SECOND_KEY = "{id}:20260708T080000Z"

BUILTIN: dict[str, Any] = {
    "registration_mode": "builtin",
    "registration_provider": PROVIDER_ID,
    "registration_target": KNOWN_TARGET,
}


async def public_calendar(db: Any, slug: str = "public", **fields: Any) -> Calendar:
    fields.setdefault("visibility", Visibility.PUBLIC)
    cal = Calendar(slug=slug, name=slug, owner_id="o", **fields)
    db.add(cal)
    await db.flush()
    return cal


async def one_off(db: Any, cal: Calendar, **fields: Any) -> Event:
    """A published one-off at 10:00 Vienna on 2026-07-01 with builtin registration."""
    fields.setdefault("status", "published")
    fields.setdefault("starts_at", START)
    fields.setdefault("timezone", "Europe/Vienna")
    for name, value in BUILTIN.items():
        fields.setdefault(name, value)
    return await seed_event(db, cal, title=fields.pop("title", "Open day"), **fields)


async def series(db: Any, cal: Calendar, **fields: Any) -> Event:
    """A published weekly (Wednesday 10:00 Vienna) series from 2026-07-01."""
    fields.setdefault("status", "published")
    fields.setdefault("title", "Weekly")
    for name, value in BUILTIN.items():
        fields.setdefault(name, value)
    rule = fields.pop("rule", WEEKLY)
    return await seed_series(db, cal, rule, "2026-07-01T10:00", "2026-07-01T11:00", **fields)


async def override(db: Any, event: Event, kind: str, original: datetime = SECOND, **fields):
    row = OccurrenceOverride(event_id=event.id, original_start=original, kind=kind, **fields)
    db.add(row)
    await db.flush()
    return row


async def moved(db: Any, event: Event, to: datetime, original: datetime = SECOND):
    return await override(
        db, event, "moved", original, starts_at=to, ends_at=to + timedelta(hours=1)
    )


async def taken(db: Any, event: Event, key: str | None, n: int) -> None:
    db.add(RegistrationCount(event_id=event.id, occurrence_key=key or str(event.id), taken=n))
    await db.flush()


async def consistent(db: Any) -> dict[tuple[Any, str], int]:
    """Every counter equals the number of seat rows it counts, and no seat lacks a counter. The
    check the plan's "counts are derived or kept consistent" asks for: it recomputes from rows.
    ``{(event_id, key): taken}``."""
    from sm_events.models import RegistrationSeat
    from sqlalchemy import func, select

    counters = {
        (row.event_id, row.occurrence_key): row.taken
        for row in (
            await db.execute(select(RegistrationCount).execution_options(populate_existing=True))
        ).scalars()
    }
    seats = {
        (event_id, key): n
        for event_id, key, n in (
            await db.execute(
                select(
                    RegistrationSeat.event_id, RegistrationSeat.occurrence_key, func.count()
                ).group_by(RegistrationSeat.event_id, RegistrationSeat.occurrence_key)
            )
        ).all()
    }
    for key, n in seats.items():
        assert counters.get(key) == n, f"counter {counters.get(key)} but {n} seats for {key}"
    for key, taken in counters.items():
        assert taken == seats.get(key, 0), (
            f"counter {taken} but {seats.get(key, 0)} seats for {key}"
        )
        assert taken >= 0
    return counters
