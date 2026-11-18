"""What the occurrences read returns, and what a caller may filter it by."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sm_events.calendar.extension_types import SourceStatus

__all__ = ["Occurrence", "OccurrenceFilters", "OccurrencePage", "PluginOccurrence"]


class Occurrence(BaseModel):
    """One thing on a calendar: a one-off, one instance of a series, or another
    source's entry. ``start``/``end`` are UTC; ``start_date``/``end_date`` are set
    for all-day occurrences only (``end_date`` exclusive, in the event's timezone)."""

    model_config = ConfigDict(frozen=True)

    source: str
    key: str
    calendar_id: uuid.UUID
    start: datetime
    end: datetime
    all_day: bool
    timezone: str
    start_date: date | None = None
    end_date: date | None = None
    title: str
    lang: str
    color: str
    url: str | None = None
    status: Literal["confirmed", "cancelled"] = "confirmed"
    type: str
    editable: bool = False
    event_id: uuid.UUID | None = None
    original_start: datetime | None = None
    event_status: str | None = None


class PluginOccurrence(Occurrence):
    """An occurrence a plugin source supplied. ``updated_at`` is the source's own timestamp
    for the item, kept only for the feeds' ``DTSTAMP``; it never appears in a response."""

    updated_at: datetime | None = Field(default=None, exclude=True)


class OccurrencePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Occurrence]
    truncated: bool
    sources: list[SourceStatus] = []
    """How each plugin source went (the built-in one is never listed). Only a console read
    carries it: a public answer may be cached and must not vary with a plugin's health."""


@dataclass(frozen=True)
class OccurrenceFilters:
    """``None`` means no filter. An id the viewer cannot see matches nothing and
    raises nothing, so existence cannot be probed."""

    calendar_ids: frozenset[uuid.UUID] | None = None
    category_ids: frozenset[uuid.UUID] | None = None
    types: frozenset[str] | None = None
    """A plugin's item is of the default type: a filter without that type excludes it."""
    sources: frozenset[str] | None = None
    """``None``: every applicable source. ``SOURCE_EVENTS`` names the built-in one."""
    locale: str | None = None
    include_unpublished: bool = True
    event_ids: frozenset[uuid.UUID] | None = None
    """Only these events' occurrences (a card reads one event). An empty set matches nothing.
    While set, plugin sources are not called: they have no event ids."""
