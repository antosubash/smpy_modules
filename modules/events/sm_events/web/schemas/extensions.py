"""The extension registry's request bodies (bounded) and responses (not)."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from sm_events.core import constants

__all__ = ["CalendarSourceIn", "CalendarSourceOut", "SourceOut", "SourcesIn", "TypeOut"]


class CalendarSourceIn(BaseModel):
    id: Annotated[str, Field(min_length=1, max_length=constants.SOURCE_ID_MAX)]
    settings: dict[str, Any] = Field(default_factory=dict)


class SourcesIn(BaseModel):
    sources: Annotated[list[CalendarSourceIn], Field(max_length=constants.SOURCES_IN_MAX)]


class CalendarSourceOut(BaseModel):
    """A source enabled on a calendar. ``settings`` is empty unless the caller can manage
    the calendar; ``installed`` is false for an id no plugin on this host provides."""

    id: str
    settings: dict[str, Any]
    installed: bool
    label_key: str | None = None


class SourceOut(BaseModel):
    id: str
    label_key: str
    color: str | None
    icon: str | None
    public: bool
    has_settings: bool
    settings_schema: dict[str, Any] | None


class TypeOut(BaseModel):
    id: str
    label_key: str
    icon: str | None
    builtin: bool
    public_fields: list[str]
    json_schema: dict[str, Any]
    defaults: dict[str, Any]
