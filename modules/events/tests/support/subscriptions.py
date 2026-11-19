"""Seeding for the subscription tests: a calendar, a subscription with a sealed address, and
calendar files built from a few properties."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sm_events.core.clock import utcnow
from sm_events.feeds.subscriptions import urls
from sm_events.models import Calendar, Subscription

CRLF = "\r\n"
URL = "https://cal.example/feed.ics"


def vevent(*extra: str, **props: str) -> list[str]:
    """One VEVENT as lines. ``props`` replace the defaults by upper-case name (a name with
    parameters is passed through ``**{"DTSTART;TZID=Europe/Vienna": "20260701T100000"}``);
    ``extra`` lines are appended."""
    base = {
        "UID": "a@x",
        "DTSTART": "20260701T100000Z",
        "DTEND": "20260701T110000Z",
        "SUMMARY": "Talk",
    }
    named = {name.split(";")[0] for name in props}
    merged = {**{k: v for k, v in base.items() if k not in named or k in props}, **props}
    return [
        "BEGIN:VEVENT",
        *(f"{name}:{value}" for name, value in merged.items() if value is not None),
        *extra,
        "END:VEVENT",
    ]


def ics(*events: list[str]) -> bytes:
    body = [line for lines in events for line in lines]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//x//EN", *body, "END:VCALENDAR"]
    return (CRLF.join(lines) + CRLF).encode()


async def seed_calendar(db: Any, slug: str = "team", tz: str = "Europe/Vienna", **kw) -> Calendar:
    calendar = Calendar(slug=slug, name=slug.title(), owner_id="o", default_timezone=tz, **kw)
    db.add(calendar)
    await db.flush()
    return calendar


async def seed_subscription(db: Any, calendar: Calendar, **fields: Any) -> Subscription:
    """A pending subscription due now, with ``url`` sealed (default :data:`URL`)."""
    url = fields.pop("url", URL)
    now = utcnow()
    values: dict[str, Any] = {
        "calendar_id": calendar.id,
        "created_by": "o",
        "url_enc": urls.seal(url),
        "url_display": urls.display_of(url),
        "label": "Work",
        "next_fetch_at": now - timedelta(minutes=1),
    }
    sub = Subscription(**{**values, **fields})
    db.add(sub)
    await db.flush()
    return sub


async def seed_item(db: Any, sub: Subscription, uid: str, start: datetime, **fields: Any) -> Any:
    """An ``ExternalItem`` inserted directly (a one-off of one hour unless told otherwise)."""
    from sm_events.models import ExternalItem

    end = fields.pop("ends_at", start + timedelta(hours=1))
    values: dict[str, Any] = {
        "subscription_id": sub.id,
        "uid": uid,
        "all_day": False,
        "starts_at": start,
        "ends_at": end,
        "timezone": "UTC",
        "span_start": start,
        "span_end": end,
        "title": uid,
        "content_hash": "0" * 64,
        "seen_generation": 1,
    }
    item = ExternalItem(**{**values, **fields})
    db.add(item)
    return item
