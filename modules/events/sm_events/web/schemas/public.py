"""Query parsing for the anonymous surface.

One answer for bad input: a malformed value is a 422 (FastAPI's own list shape for a type error, the
``{"detail", "code"}`` envelope for a range the read refuses), never a guess. Nothing here reveals
whether an id exists: a calendar or category id the public may not see matches nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query

from sm_events.core import constants, locales
from sm_events.web.schemas._fields import SupportedInstant

__all__ = ["PublicOccurrenceParams", "PublicOccurrenceQuery", "public_occurrence_query"]


@dataclass(frozen=True)
class PublicOccurrenceQuery:
    start: SupportedInstant
    end: SupportedInstant
    calendar_ids: frozenset[uuid.UUID] | None
    category_ids: frozenset[uuid.UUID] | None
    locale: str


def public_occurrence_query(
    start: Annotated[SupportedInstant, Query()],
    end: Annotated[SupportedInstant, Query()],
    calendar: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CALENDARS_MAX)] = None,
    category: Annotated[list[uuid.UUID] | None, Query(max_length=constants.CATEGORIES_MAX)] = None,
    locale: Annotated[str | None, Query(max_length=constants.LOCALE_MAX)] = None,
    type: Annotated[list[str] | None, Query(max_length=20)] = None,
) -> PublicOccurrenceQuery:
    """The query string as one value. ``type`` is accepted and ignored (the grid's filter bar
    sends it); an unknown ``locale`` is the default language."""
    return PublicOccurrenceQuery(
        start=start,
        end=end,
        calendar_ids=frozenset(calendar) if calendar else None,
        category_ids=frozenset(category) if category else None,
        locale=locale if locale in locales.supported() else locales.default(),  # type: ignore[arg-type]
    )


PublicOccurrenceParams = Annotated[PublicOccurrenceQuery, Depends(public_occurrence_query)]
