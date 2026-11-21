"""What the occurrences read returns, and what a caller may filter it by."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["Occurrence", "OccurrenceFilters", "OccurrencePage"]


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


class OccurrencePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Occurrence]
    truncated: bool


@dataclass(frozen=True)
class OccurrenceFilters:
    """``None`` means no filter. An id the viewer cannot see matches nothing and
    raises nothing, so existence cannot be probed."""

    calendar_ids: frozenset[uuid.UUID] | None = None
    category_ids: frozenset[uuid.UUID] | None = None
    types: frozenset[str] | None = None
    locale: str | None = None
    include_unpublished: bool = True
