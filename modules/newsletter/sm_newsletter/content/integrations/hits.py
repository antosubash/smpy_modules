"""What a card or media search answers, whichever module it came from."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from simple_module_db import like_contains_pattern

MAX_QUERY = 100
SEARCH_LIMIT = 20
MAX_SOURCE_ID = 2**31 - 1
"""Articles and pages have 32-bit ids: a larger one would overflow the driver, not miss."""


@dataclass(frozen=True)
class CardHit:
    kind: Literal["article", "page"]
    source_id: int
    title: str
    excerpt: str
    image_url: str
    """As the contract returns it: may be site-relative; the renderer makes it absolute."""
    url: str
    """Site-relative, as the contract returns it (ruling R6)."""
    locale: str


@dataclass(frozen=True)
class EventHit:
    """An event card, renamed from ``sm_events.contracts.cards.EventCard``."""

    kind: Literal["event"]
    source_id: str
    """The event's id as canonical UUID text. Stored in the draft only: never rendered."""
    title: str
    excerpt: str
    image_url: str
    url: str
    """Site-relative, as the contract returns it; the renderer makes it absolute."""
    ics_url: str
    locale: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    start_date: date | None
    end_date: date | None
    timezone: str
    attendance_mode: str
    place: str
    """``"venue, address"`` or ``""``."""
    cancelled: bool


@dataclass(frozen=True)
class MediaHit:
    id: int
    filename: str
    url: str
    """The path the contract returns; the renderer makes it absolute."""


def like_pattern(q: str) -> str:
    """``%q%`` for a ``LIKE ... ESCAPE '\\'``: ``q`` stripped, at most
    :data:`MAX_QUERY` characters, with ``\\``, ``%`` and ``_`` escaped."""
    return like_contains_pattern(q.strip()[:MAX_QUERY])
