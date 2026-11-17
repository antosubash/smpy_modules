"""Calendar request bodies (bounded) and responses (not)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from sm_events.core import constants, timezones
from sm_events.models import Visibility
from sm_events.web.schemas._fields import Color, Slug, lower_color

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, Field(max_length=2000)]


def _known_timezone(value: str | None) -> str | None:
    if value is not None and not timezones.is_known(value):
        raise ValueError("not a known IANA timezone")
    return value


class CalendarCreate(BaseModel):
    name: Name
    slug: Slug | None = None
    color: Color = constants.DEFAULT_COLOR
    description: Description | None = None
    visibility: Visibility = Visibility.PRIVATE
    default_timezone: str | None = Field(default=None, max_length=constants.TZ_MAX)

    _lower_color = field_validator("color", mode="before")(lower_color)
    _tz = field_validator("default_timezone")(_known_timezone)


class CalendarPatch(BaseModel):
    """Every field optional; ``visibility`` is set only by ``PUT .../visibility``."""

    name: Name | None = None
    slug: Slug | None = None
    color: Color | None = None
    description: Description | None = None
    default_timezone: str | None = Field(default=None, max_length=constants.TZ_MAX)

    _lower_color = field_validator("color", mode="before")(lower_color)
    _tz = field_validator("default_timezone")(_known_timezone)

    @model_validator(mode="after")
    def _no_null_for_required(self) -> CalendarPatch:
        for field in ("name", "slug", "color", "default_timezone"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class VisibilityIn(BaseModel):
    visibility: Visibility


class OwnerIn(BaseModel):
    owner_id: Annotated[str, Field(min_length=1, max_length=64)]


class CalendarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    color: str
    description: str | None
    visibility: str
    owner_id: str
    default_timezone: str
    sources: list[Any]
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None
    can_edit: bool = False
    can_own: bool = False
    can_write_events: bool = False
    can_publish: bool = False
