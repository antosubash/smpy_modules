"""Query parsing for ``GET /occurrences`` and the event list's paging.

``start`` and ``end`` must be timezone-aware (an offset or ``Z``): a naive one is a
422, never guessed. The range bounds themselves are the read's
(:func:`sm_events.calendar.occurrences.occurrences`), not the router's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.core import constants
from sm_events.web.schemas._fields import SupportedInstant

__all__ = ["OccurrenceParams", "OccurrenceQuery", "occurrence_query"]


@dataclass(frozen=True)
class OccurrenceQuery:
    start: SupportedInstant
    end: SupportedInstant
    filters: OccurrenceFilters


def occurrence_query(
    start: Annotated[SupportedInstant, Query()],
    end: Annotated[SupportedInstant, Query()],
    calendar: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CALENDARS_MAX)] = None,
    category: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CATEGORIES_MAX)] = None,
    types: Annotated[list[str] | None, Query(alias="type", max_length=20)] = None,
    sources: Annotated[list[str] | None, Query(alias="source", max_length=20)] = None,
    locale: Annotated[str | None, Query(max_length=constants.LOCALE_MAX)] = None,
    include_unpublished: Annotated[bool, Query()] = True,
) -> OccurrenceQuery:
    """The query string as one value; repeated parameters become sets."""
    return OccurrenceQuery(
        start=start,
        end=end,
        filters=OccurrenceFilters(
            calendar_ids=frozenset(calendar) if calendar else None,
            category_ids=frozenset(category) if category else None,
            types=frozenset(types) if types else None,
            sources=frozenset(sources) if sources else None,
            locale=locale,
            include_unpublished=include_unpublished,
        ),
    )


OccurrenceParams = Annotated[OccurrenceQuery, Depends(occurrence_query)]
