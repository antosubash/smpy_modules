"""Plugin sources in a feed: what they put on a calendar, as plain ``VEVENT``s.

A feed asks for ``[now - FEED_DAYS_BACK, now + FEED_DAYS_AHEAD)`` (396 days), so it calls the
plugin runner directly rather than the occurrences read (whose range stops at 366): a source
accepts any window up to ``SOURCE_WINDOW_MAX_DAYS``. The public feeds call public sources with
no viewer; the private feed calls every enabled source for the link's owner, or none when that
person cannot be built (the feed is still served).

Each item is one instance, never a rule: ``UID <source>:<key>`` (a repeated UID keeps the
first), ``DTSTAMP`` the source's own ``updated_at`` or else the item's start (so the body, and
the public feed's ``ETag``, stays deterministic), ``SEQUENCE 0``. Plugin components count
against ``FEED_MAX_COMPONENTS`` *after* this module's own events, so a cut drops them first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import icalendar
from simple_module_core.resources import ResourcePrincipal

from sm_events.calendar.extension_types import SourceViewer
from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters
from sm_events.calendar.plugin_runner import run_sources
from sm_events.calendar.plugin_scope import plugin_calls
from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.sanitize import single_line

__all__ = ["PluginFeed", "plugin_feed", "plugin_vevents"]


@dataclass(frozen=True)
class PluginFeed:
    events: list[icalendar.Event]
    truncated: bool


def _stamp(item: Occurrence) -> datetime:
    stamped = getattr(item, "updated_at", None)
    return (stamped or item.start).astimezone(UTC)


def plugin_vevents(
    items: Sequence[Occurrence], *, absolute: Callable[[str], str]
) -> list[icalendar.Event]:
    """One ``VEVENT`` per item; ``absolute`` turns a same-origin path into an absolute URL."""
    out: list[icalendar.Event] = []
    seen: set[str] = set()
    for item in items:
        uid = f"{item.source}:{item.key}"
        if uid in seen:
            continue
        seen.add(uid)
        event = icalendar.Event()
        event.add("uid", uid)
        event.add("dtstamp", _stamp(item))
        event.add("summary", single_line(item.title))
        event.add("status", "CANCELLED" if item.status == "cancelled" else "CONFIRMED")
        if item.all_day and item.start_date is not None and item.end_date is not None:
            event.add("dtstart", item.start_date)
            event.add("dtend", item.end_date)
        else:
            event.add("dtstart", item.start.astimezone(UTC))
            event.add("dtend", item.end.astimezone(UTC))
        if item.url is not None:
            event.add("url", absolute(item.url) if item.url.startswith("/") else item.url)
        event.add("sequence", 0)
        out.append(event)
    return out


async def plugin_feed(
    db: Any,
    *,
    who: ResourcePrincipal,
    viewer: SourceViewer | None,
    calendar_id: uuid.UUID | None,
    now: datetime,
    locale: str,
    default_locale: str,
    room: int,
    absolute: Callable[[str], str],
) -> PluginFeed:
    """The plugin ``VEVENT``s of ``calendar_id`` (every calendar ``who`` can see when ``None``),
    at most ``room`` of them (what the cap leaves after this module's own events).

    ``who`` is the anonymous principal for a public feed (only public sources are called, with
    no viewer) or the private link's owner. Never raises for a plugin's doing."""
    if room <= 0:
        return PluginFeed([], False)
    filters = OccurrenceFilters(
        calendar_ids=None if calendar_id is None else frozenset({calendar_id})
    )
    calls, _skipped = await plugin_calls(db, who, viewer, filters)
    if not calls:
        return PluginFeed([], False)
    ran = await run_sources(
        db,
        calls,
        tenant_id=bound_tenant(),
        viewer=None if who.user_id is None else viewer,
        start=now - timedelta(days=constants.FEED_DAYS_BACK),
        end=now + timedelta(days=constants.FEED_DAYS_AHEAD),
        locale=locale,
        default_locale=default_locale,
    )
    events = plugin_vevents(ran.items, absolute=absolute)
    cut = len(events) > room
    return PluginFeed(events[:room], cut or ran.truncated)
