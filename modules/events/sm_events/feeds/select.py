"""The feed read: public events with their rules, overrides, texts and parents.

Everything starts from :func:`~sm_events.core.access.public.public_events`, so a draft, an
event of an internal or private calendar, a trashed row or another tenant's never reaches a
feed. It reads rows, not occurrences: a series is handed over as its master with **all** its
overrides (an ``EXDATE`` outside the window still hides an instance a client expands).

**Window and caps (Ruling 25).** A calendar feed holds the masters that meet
``[now - FEED_DAYS_BACK, now + FEED_DAYS_AHEAD)`` (a one-off by its span, a series by its first
start and ``recurrence_until``), by start, at most ``FEED_MAX_EVENTS`` of them and
``FEED_MAX_COMPONENTS`` ``VEVENT`` components. When a series would cross the component cap, it
and every later master are dropped, never a series without its ``EXDATE``s. ``truncated``
says anything was cut.

Four statements however many events: the events, the overrides of the series, the categories
and the public parents (the texts are a fifth, in the shared helper).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlmodel import col

from sm_events.content.public_read import pick_text
from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.access.public import public_events
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.ics_event import FeedEvent
from sm_events.models import Category, Event, OccurrenceOverride

__all__ = ["FeedRead", "feed_events", "single_event"]

UrlFor = Callable[[str, str], str]


@dataclass(frozen=True)
class FeedRead:
    items: list[FeedEvent]
    truncated: bool


def _in_window(lo: datetime, hi: datetime) -> Any:
    one_off = and_(col(Event.rrule).is_(None), Event.ends_at > lo, Event.starts_at < hi)
    series = and_(
        col(Event.rrule).is_not(None),
        Event.starts_at < hi,
        or_(col(Event.recurrence_until).is_(None), Event.recurrence_until > lo),
    )
    return or_(one_off, series)


async def _overrides(
    db: Any, events: Sequence[Event]
) -> tuple[dict[uuid.UUID, list[OccurrenceOverride]], uuid.UUID | None, datetime | None]:
    """``{series id: its overrides}`` and, when the read hit its bound, the id of the series whose
    overrides may be incomplete (that one and every id after it, in ``event_id`` order, are cut).

    At most ``FEED_MAX_COMPONENTS + 1`` rows are loaded in all, ordered by ``(event_id,
    original_start)``: more overrides than the cap could ever emit are never read."""
    ids = [e.id for e in events if e.rrule]
    found: dict[uuid.UUID, list[OccurrenceOverride]] = {i: [] for i in ids}
    if not ids:
        return found, None, None
    stmt = (
        select(OccurrenceOverride)
        .where(
            OccurrenceOverride.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            col(OccurrenceOverride.event_id).in_(ids),
        )
        .order_by(col(OccurrenceOverride.event_id), col(OccurrenceOverride.original_start))
        .limit(constants.FEED_MAX_COMPONENTS + 1)
    )
    rows = list((await db.execute(stmt)).scalars())
    cut_at: uuid.UUID | None = None
    first_missing: datetime | None = None
    if len(rows) > constants.FEED_MAX_COMPONENTS:
        first_missing = rows[constants.FEED_MAX_COMPONENTS].original_start
        rows = rows[: constants.FEED_MAX_COMPONENTS]
        cut_at = rows[-1].event_id if rows else None
    for row in rows:
        found[row.event_id].append(row)
    return found, cut_at, first_missing


async def _categories(db: Any, events: Sequence[Event]) -> dict[uuid.UUID, Category]:
    ids = {e.category_id for e in events if e.category_id}
    if not ids:
        return {}
    stmt = select(Category).where(
        Category.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        col(Category.id).in_(ids),
    )
    return {c.id: c for c in (await db.execute(stmt)).scalars()}


async def _parent_uids(db: Any, events: Iterable[Event], visible: Any) -> dict[uuid.UUID, str]:
    """The UID of each parent that is itself in ``visible`` (the select the feed reads from);
    a hidden parent is simply absent."""
    ids = {e.parent_id for e in events if e.parent_id}
    if not ids:
        return {}
    stmt = visible.with_only_columns(Event.id, Event.uid).where(col(Event.id).in_(ids))
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


def _category_name(cat: Category | None, locale: str, default: str) -> str | None:
    if cat is None or not cat.names:
        return None
    return cat.names.get(locale) or cat.names.get(default) or cat.names[min(cat.names)]


async def _items(
    db: Any,
    events: Sequence[Event],
    *,
    locale: str,
    default_locale: str,
    url_for: UrlFor,
    drop_cut: bool,
    visible: Any,
) -> tuple[list[FeedEvent], bool]:
    """The items, and whether the override bound cut something. In a calendar feed a series
    whose overrides were cut is dropped (``drop_cut``); a single event's file keeps what was read
    and says so."""
    texts = await texts_of(db, [e.id for e in events])
    overrides, cut_at, first_missing = await _overrides(db, events)
    cut = first_missing is not None
    if cut_at is not None and drop_cut:
        # A series whose overrides were cut must not be emitted: without its EXDATEs a client
        # would resurrect skipped occurrences. Its row and every later one (by id) are dropped.
        events = [e for e in events if not e.rrule or e.id < cut_at]
    categories = await _categories(db, events)
    parents = await _parent_uids(db, events, visible)
    items: list[FeedEvent] = []
    for event in events:
        if not texts[event.id]:  # an event always has its default text; skip a broken one
            continue
        text = pick_text(texts[event.id], locale, default_locale)
        items.append(
            FeedEvent(
                event=event,
                text=text,
                overrides=tuple(overrides.get(event.id, ())),
                url=url_for(text.slug, text.locale),
                category=_category_name(categories.get(event.category_id), locale, default_locale),  # type: ignore[arg-type]
                parent_uid=parents.get(event.parent_id) if event.parent_id else None,
                ends_before=first_missing if cut and not drop_cut and event.rrule else None,
            )
        )
    return items, cut


def _components(item: FeedEvent) -> int:
    """What a series costs against the component cap: the master and every override, a skip
    (an ``EXDATE``) included, so the file's size is bounded by the cap however it is made."""
    return 1 + len(item.overrides) if item.event.rrule else 1


async def feed_events(
    db: Any,
    *,
    calendar_id: uuid.UUID | None,
    locale: str,
    default_locale: str,
    now: datetime,
    url_for: UrlFor,
    events: Any = None,
) -> FeedRead:
    """The feed's items for ``calendar_id`` (every calendar ``events`` reaches when ``None``).

    ``events`` is the ``SELECT Event`` the feed reads from: the public gate's by default, or a
    caller's own narrower select (a private feed passes what its owner may see). It is always
    held to the bound tenant here as well, so a select built without that predicate cannot
    cross tenants."""
    lo = now - timedelta(days=constants.FEED_DAYS_BACK)
    hi = now + timedelta(days=constants.FEED_DAYS_AHEAD)
    visible = public_events() if events is None else events.where(Event.tenant_id == bound_tenant())
    stmt = visible.where(_in_window(lo, hi))
    if calendar_id is not None:
        stmt = stmt.where(Event.calendar_id == calendar_id)
    stmt = stmt.order_by(col(Event.starts_at), col(Event.id)).limit(constants.FEED_MAX_EVENTS + 1)
    events = list((await db.execute(stmt)).scalars().all())
    truncated = len(events) > constants.FEED_MAX_EVENTS
    items, cut = await _items(
        db,
        events[: constants.FEED_MAX_EVENTS],
        locale=locale,
        default_locale=default_locale,
        url_for=url_for,
        drop_cut=True,
        visible=visible,
    )
    truncated = truncated or cut
    kept: list[FeedEvent] = []
    used = 0
    for item in items:
        used += _components(item)
        if used > constants.FEED_MAX_COMPONENTS:
            truncated = True
            break
        kept.append(item)
    return FeedRead(items=kept, truncated=truncated)


async def single_event(
    db: Any, event: Event, *, locale: str, default_locale: str, url_for: UrlFor
) -> FeedRead:
    """One event, whole: no window, its overrides up to the component cap (``truncated`` when
    there are more). The caller has already passed it through the gate (``event_by_slug``)."""
    items, cut = await _items(
        db,
        [event],
        locale=locale,
        default_locale=default_locale,
        url_for=url_for,
        drop_cut=False,
        visible=public_events(),
    )
    return FeedRead(items=items, truncated=cut)
