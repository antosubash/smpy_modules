"""Calendar HTTP setup shared by the API tests."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sm_events.calendar import rrule
from sm_events.calendar.times import localize, to_span
from sm_events.models import (
    Calendar,
    Category,
    Event,
    EventText,
    OccurrenceOverride,
    Visibility,
)

from tests.support.app import as_user

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
BASE = "/api/events/calendars"
OWNER = as_user("o", V, E)
OWNER_P = as_user("o", V, E, P)
VIEWER = as_user("v", V)
EDITOR = as_user("e", V, E)
MANAGER = as_user("m", V, M)
SV = as_user("sv", V)
SE = as_user("se", V)


async def make(client, headers=OWNER, **body):
    body.setdefault("name", "Team")
    got = await client.post(BASE, json=body, headers=headers)
    assert got.status_code == 201, got.text
    return got.json()


async def bare_event(db: Any, calendar: Calendar, **fields: Any) -> Event:
    """An ``Event`` row with no text (what ``create_event`` inserts before its
    texts). ``fields`` are ``Event`` columns; the defaults are a one-hour draft on
    2026-07-01 in UTC."""
    start = fields.pop("starts_at", datetime(2026, 7, 1, 10, tzinfo=UTC))
    fields.setdefault("ends_at", start + timedelta(hours=1))
    fields.setdefault("timezone", "UTC")
    fields.setdefault("uid", f"{uuid.uuid4()}@simple-module-events")
    event = Event(calendar_id=calendar.id, starts_at=start, **fields)
    db.add(event)
    await db.flush()
    return event


async def seed_event(
    db: Any,
    calendar: Calendar,
    *,
    title: str = "Event",
    locale: str = "en",
    slug: str | None = None,
    **fields: Any,
) -> Event:
    """Insert an event and its text straight into the database (no service, no
    revision). ``fields`` are ``Event`` columns; the defaults are a one-hour
    draft on 2026-07-01 in UTC."""
    event = await bare_event(db, calendar, **fields)
    db.add(
        EventText(
            event_id=event.id,
            locale=locale,
            slug=slug or f"event-{event.id.hex[:12]}",
            title=title,
        )
    )
    await db.flush()
    return event


async def seed_series(
    db: Any,
    calendar: Calendar,
    text: str,
    start: str,
    end: str,
    *,
    tz: str = "Europe/Vienna",
    all_day: bool = False,
    **fields: Any,
) -> Event:
    """A recurring event, its span and ``recurrence_until`` derived the way the
    service will derive them. ``start``/``end`` are local wall-clock input."""
    span = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=True)
    rule = rrule.parse(text, all_day=all_day, timezone=tz)
    until = rrule.validate(rule, span, all_day=all_day, timezone=tz)
    return await seed_event(
        db,
        calendar,
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone=tz,
        all_day=all_day,
        rrule=rule.text,
        recurrence_until=until,
        **fields,
    )


@dataclass
class PublicFixture:
    """What the public surface's tests read: a cast chosen so that every way a row
    could leak (status, visibility, trash, parent, category, language) has a member.

    ``pub`` is the one public calendar. The five events the anonymous visitor may see are
    :attr:`public_events`; everything else in :attr:`hidden` must never reach them.
    """

    pub: Calendar
    internal: Calendar
    private: Calendar
    gone: Calendar
    one_off: Event
    series: Event
    draft: Event
    in_review: Event
    scheduled: Event
    trashed: Event
    conf: Event
    talk: Event
    secret_talk: Event
    draft_parent: Event
    orphan: Event
    internal_event: Event
    private_event: Event
    gone_event: Event
    public_cat: Category
    draft_cat: Category
    series_overrides: dict[str, OccurrenceOverride]
    tag: str = ""
    slugs: dict[str, str] = field(default_factory=dict)

    @property
    def public_events(self) -> list[Event]:
        return [self.one_off, self.series, self.conf, self.talk, self.orphan]

    @property
    def hidden(self) -> dict[str, Event]:
        """The events that must never be public, by the name the leak tests use."""
        return {
            "draft": self.draft,
            "in_review": self.in_review,
            "scheduled": self.scheduled,
            "internal": self.internal_event,
            "private": self.private_event,
            "trashed": self.trashed,
            "calendar_trashed": self.gone_event,
            "secret_talk": self.secret_talk,
            "draft_parent": self.draft_parent,
        }

    def slug(self, event: Event, locale: str = "en") -> str:
        return self.slugs[f"{event.id}:{locale}"]


async def seed_public_fixture(db: Any, tag: str = "") -> PublicFixture:
    """The cast above in the bound tenant. ``tag`` is added to every slug, title and
    calendar slug, so the same fixture can be seeded in two tenants with distinct text."""
    slugs: dict[str, str] = {}

    async def calendar(name: str, visibility: Visibility) -> Calendar:
        cal = Calendar(
            slug=f"{name}{tag}", name=f"{name.title()}{tag}", owner_id="o", visibility=visibility
        )
        db.add(cal)
        await db.flush()
        return cal

    async def event(cal: Calendar, name: str, **fields: Any) -> Event:
        fields.setdefault("status", "published")
        slug = f"{name}{tag}"
        made = await seed_event(db, cal, title=f"{name.title()}{tag}", slug=slug, **fields)
        slugs[f"{made.id}:en"] = slug
        return made

    async def category(name: str) -> Category:
        cat = Category(slug=f"{name}{tag}", names={"en": f"{name}{tag}"})
        db.add(cat)
        await db.flush()
        return cat

    pub = await calendar("pub", Visibility.PUBLIC)
    internal = await calendar("internal", Visibility.INTERNAL)
    private = await calendar("private", Visibility.PRIVATE)
    gone = await calendar("gone", Visibility.PUBLIC)
    public_cat, draft_cat = await category("public-cat"), await category("draft-cat")

    one_off = await event(pub, "one-off", category_id=public_cat.id)
    series = await seed_series(
        db,
        pub,
        "FREQ=WEEKLY;COUNT=8",
        "2026-03-16T10:00",
        "2026-03-16T11:00",
        title=f"Series{tag}",
        slug=f"series{tag}",
        status="published",
    )
    slugs[f"{series.id}:en"] = f"series{tag}"
    zone = ZoneInfo("Europe/Vienna")

    def week(n: int) -> datetime:
        return localize(datetime(2026, 3, 16, 10) + timedelta(weeks=n - 1), zone)

    overrides = {
        "moved": OccurrenceOverride(
            event_id=series.id,
            original_start=week(3),
            kind="moved",
            starts_at=week(3) + timedelta(hours=1),
            ends_at=week(3) + timedelta(hours=2),
        ),
        "cancelled": OccurrenceOverride(
            event_id=series.id, original_start=week(4), kind="cancelled"
        ),
        "skipped": OccurrenceOverride(event_id=series.id, original_start=week(5), kind="skipped"),
    }
    db.add_all(overrides.values())

    draft = await event(pub, "draft", status="draft", category_id=draft_cat.id)
    in_review = await event(pub, "in-review", status="in_review")
    scheduled = await event(
        pub, "scheduled", status="draft", publish_at=datetime(2030, 1, 1, tzinfo=UTC)
    )
    trashed = await event(pub, "trashed")
    await db.delete(trashed)
    conf = await event(pub, "conf")
    talk = await event(pub, "talk", parent_id=conf.id)
    secret_talk = await event(pub, "secret-talk", parent_id=conf.id, status="draft")
    draft_parent = await event(pub, "draft-parent", status="draft")
    orphan = await event(pub, "orphan", parent_id=draft_parent.id)
    internal_event = await event(internal, "internal-event", category_id=draft_cat.id)
    private_event = await event(private, "private-event")
    gone_event = await event(gone, "gone-event")
    await db.delete(gone)

    for target in (one_off, series):
        text = f"{slugs[f'{target.id}:en']}-de"
        db.add(EventText(event_id=target.id, locale="de", slug=text, title=f"{text.title()}"))
        slugs[f"{target.id}:de"] = text
    await db.flush()
    return PublicFixture(
        pub=pub,
        internal=internal,
        private=private,
        gone=gone,
        one_off=one_off,
        series=series,
        draft=draft,
        in_review=in_review,
        scheduled=scheduled,
        trashed=trashed,
        conf=conf,
        talk=talk,
        secret_talk=secret_talk,
        draft_parent=draft_parent,
        orphan=orphan,
        internal_event=internal_event,
        private_event=private_event,
        gone_event=gone_event,
        public_cat=public_cat,
        draft_cat=draft_cat,
        series_overrides=overrides,
        tag=tag,
        slugs=slugs,
    )
