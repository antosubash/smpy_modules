"""Occurrence overrides and the series-change preview: bodies and responses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sm_events.calendar.times import Span, to_local
from sm_events.core import constants
from sm_events.models import OccurrenceOverride
from sm_events.models.enums import OVERRIDE_KINDS, OverrideKind
from sm_events.web.schemas._fields import MultiLine
from sm_events.web.schemas.events_in import Revision, RuleText, TimesIn

Note = Annotated[str, Field(max_length=constants.NOTE_MAX), MultiLine]
Wall = Annotated[str, Field(max_length=40)]


def in_range(value: datetime) -> datetime:
    """An instant between the years a calendar means; ``ValueError`` (a 422) beyond."""
    try:
        year = value.astimezone(UTC).year
    except OverflowError:
        year = 0
    if not constants.ORIGINAL_START_MIN_YEAR <= year < constants.ORIGINAL_START_MAX_YEAR:
        raise ValueError("outside the supported years")
    return value


class OverrideIn(BaseModel):
    """One occurrence of a series, named by its original UTC start.

    ``moved`` changes only the start and end (local wall clock, in the event's
    timezone) and needs both; ``skipped`` and ``cancelled`` take neither. Any
    other field is refused."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: Revision
    original_start: AwareDatetime
    kind: Literal[*OVERRIDE_KINDS]  # type: ignore[valid-type]
    start: Wall | None = None
    end: Wall | None = None
    note: Note | None = None

    @field_validator("original_start")
    @classmethod
    def _sane_year(cls, value: datetime) -> datetime:
        return in_range(value)

    @model_validator(mode="after")
    def _times_iff_moved(self) -> OverrideIn:
        moved = self.kind == OverrideKind.MOVED.value
        if moved and (self.start is None or self.end is None):
            raise ValueError("a moved occurrence needs start and end")
        if not moved and (self.start is not None or self.end is not None):
            raise ValueError("only a moved occurrence takes start and end")
        return self


class OverrideOut(BaseModel):
    id: int
    original_start: datetime
    kind: str
    starts_at: datetime | None
    ends_at: datetime | None
    start_local: str | None = None
    end_local: str | None = None
    note: str | None


class OverrideResult(OverrideOut):
    """What writing an override answers: the override and the event's new revision,
    which the next write must quote."""

    event_revision: int


def override_out(row: OccurrenceOverride, *, all_day: bool, timezone: str) -> OverrideOut:
    """A stored override, with a moved one's span in the event's local wall clock."""
    local: tuple[str | None, str | None] = (None, None)
    if row.starts_at is not None and row.ends_at is not None:
        local = to_local(Span(row.starts_at, row.ends_at), all_day=all_day, timezone=timezone)
    return OverrideOut(
        id=row.id or 0,
        original_start=row.original_start,
        kind=row.kind,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        start_local=local[0],
        end_local=local[1],
        note=row.note,
    )


class PreviewIn(BaseModel):
    """A schedule to try: the next ``count`` occurrences after ``after``, and, with
    ``event_id``, the overrides of that event the schedule would orphan. An existing
    event needs the right to change it (the notes of its overrides are for writers);
    ``calendar_id`` names the calendar of a new event, which needs ``write_events``."""

    model_config = ConfigDict(extra="forbid")

    times: TimesIn
    rrule: RuleText | None = None
    event_id: uuid.UUID | None = None
    calendar_id: uuid.UUID | None = None
    after: AwareDatetime | None = None
    count: Annotated[int, Field(ge=1, le=constants.PREVIEW_MAX)] = constants.PREVIEW_DEFAULT

    @field_validator("after")
    @classmethod
    def _sane_year(cls, value: datetime | None) -> datetime | None:
        return value if value is None else in_range(value)


class PreviewOccurrence(BaseModel):
    start: datetime
    end: datetime
    start_local: str
    end_local: str


class PreviewOut(BaseModel):
    occurrences: list[PreviewOccurrence]
    recurrence_until: datetime | None
    orphaned: list[OverrideOut]
