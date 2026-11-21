"""Event request bodies: bounded, and speaking local wall-clock times.

``times`` carries a local wall clock and an IANA ``timezone`` and never UTC:
``start``/``end`` are ``YYYY-MM-DDTHH:MM[:SS]`` for a timed event and
``YYYY-MM-DD`` (``end`` the inclusive last day) for an all-day one. The service
converts and bounds them (:mod:`sm_events.calendar.times`), so a refusal carries
its own error code.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from sm_events.core import constants
from sm_events.core.errors import ImmutableField
from sm_events.models.enums import ATTENDANCE_MODES, DEFAULT_EVENT_TYPE
from sm_events.web.schemas._fields import HttpUrl, ImageRef, MultiLine, SingleLine, TimezoneName
from sm_events.web.schemas.registration import RegistrationIn
from sm_events.web.schemas.texts import TextIn

LocaleKey = Annotated[str, Field(min_length=1, max_length=constants.LOCALE_MAX)]
Venue = Annotated[str, Field(max_length=constants.VENUE_MAX), SingleLine]
Organiser = Annotated[str, Field(max_length=constants.ORGANISER_MAX), SingleLine]
Address = Annotated[str, Field(max_length=constants.ADDRESS_MAX), MultiLine]
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
Revision = Annotated[int, Field(ge=1, le=2**31 - 1)]
# Looser than RRULE_MAX_LEN (500): a rule of 501 to 1000 characters reaches the parser, which
# refuses it with its own `invalid_rrule`; only beyond this is it a bare schema 422.
RuleText = Annotated[str, Field(max_length=constants.RRULE_INPUT_MAX)]
TypeName = Annotated[str, Field(min_length=1, max_length=constants.TYPE_NAME_MAX)]


class Expected(BaseModel):
    """The revision the caller last saw; a different one is 409 ``stale``."""

    expected_revision: Revision


class TimesIn(BaseModel):
    all_day: bool = False
    timezone: TimezoneName
    start: Annotated[str, Field(max_length=constants.TIMES_FIELD_MAX)]
    end: Annotated[str, Field(max_length=constants.TIMES_FIELD_MAX)]


class _Fields(BaseModel):
    """The writable columns every event body shares."""

    rrule: RuleText | None = None
    cancelled: bool = False
    attendance_mode: Literal[*ATTENDANCE_MODES] = "in_person"  # type: ignore[valid-type]
    venue_name: Venue | None = None
    address: Address | None = None
    online_url: HttpUrl | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    category_id: uuid.UUID | None = None
    organiser: Organiser | None = None
    image: ImageRef | None = None
    registration_url: HttpUrl | None = None
    """The older way to say "register at this link"; it sets mode ``external``. ``registration``
    is the whole of it; a URL beside it must agree."""
    registration: RegistrationIn | None = None


class EventCreate(_Fields):
    calendar_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    type: TypeName = DEFAULT_EVENT_TYPE
    extra: dict[str, Any] = Field(default_factory=dict)
    """The type's own data; validated against its model on write (size and unknown keys too)."""
    times: TimesIn
    texts: Annotated[dict[LocaleKey, TextIn], Field(min_length=1, max_length=constants.TEXTS_MAX)]


_IMMUTABLE = ("calendar_id", "parent_id", "type")
_NOT_NULL = ("times", "cancelled", "attendance_mode", "texts", "extra", "registration")


class EventPatch(_Fields):
    """Every field optional (``exclude_unset`` semantics): a field the body leaves
    out is untouched, and ``null`` clears a nullable one. ``texts`` replaces each
    language it names, and ``null`` deletes that language's text."""

    expected_revision: Revision
    times: TimesIn | None = None
    texts: (
        Annotated[
            dict[LocaleKey, TextIn | None], Field(min_length=1, max_length=constants.TEXTS_MAX)
        ]
        | None
    ) = None
    drop_orphaned_overrides: bool = False
    extra: dict[str, Any] | None = None
    """Replaces the whole ``extra``, validated against the event's type. Left out, the stored
    value is untouched, byte for byte."""

    @model_validator(mode="before")
    @classmethod
    def _immutable(cls, data: Any) -> Any:
        if isinstance(data, dict) and any(name in data for name in _IMMUTABLE):
            raise ImmutableField
        return data

    @model_validator(mode="after")
    def _no_null_for_required(self) -> EventPatch:
        for name in _NOT_NULL:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
