"""What a plugin sees: the types its sources and event types are written against.

Everything here is re-exported by :mod:`sm_events.contracts.extensions`, which is the
only path a plugin imports. A plugin never receives an ORM object or a request, only
these frozen values, and its database handle is a read-only session on a connection of its own
(see :mod:`sm_events.calendar.plugins.plugin_isolation`).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sm_events.core import constants

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "EventType",
    "NoExtra",
    "SettingsContext",
    "Source",
    "SourceCalendar",
    "SourceContext",
    "SourceError",
    "SourceOccurrence",
    "SourceSettingsError",
    "SourceStatus",
    "SourceViewer",
]


class SourceOccurrence(BaseModel):
    """One entry a source puts on a calendar. Timed (``start`` and ``end``, aware) or
    all-day (``all_day`` with ``start_date`` and ``end_date``, the end exclusive). It
    carries no ``source``, ``calendar_id``, ``editable``, ``type`` or ``event_id``:
    the read fills those in, so a source cannot claim another's id or calendar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(
        min_length=1, max_length=constants.SOURCE_KEY_MAX, pattern=constants.SOURCE_KEY_PATTERN
    )
    title: str = Field(min_length=1, max_length=constants.SOURCE_TITLE_MAX)
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = None
    url: str | None = Field(default=None, max_length=constants.SOURCE_URL_MAX)
    color: str | None = Field(default=None, pattern=constants.COLOR_PATTERN)
    status: Literal["confirmed", "cancelled"] = "confirmed"
    lang: str | None = Field(default=None, max_length=constants.LOCALE_MAX)
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SourceViewer:
    """The signed-in person a read is for. ``None`` on every public surface."""

    user_id: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    role_map: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class SourceCalendar:
    id: uuid.UUID
    slug: str
    name: str
    visibility: str
    default_timezone: str
    color: str


@dataclass(frozen=True)
class SourceContext:
    tenant_id: str
    viewer: SourceViewer | None
    calendar: SourceCalendar
    settings: BaseModel | None
    locale: str
    default_locale: str
    limit: int
    db: AsyncSession


SettingsPath = tuple[str | int, ...]


@dataclass(frozen=True)
class SettingsContext:
    tenant_id: str
    viewer: SourceViewer
    calendar: SourceCalendar
    db: AsyncSession
    preserved: tuple[SettingsPath, ...] = ()
    """Paths ``restore_settings`` filled in from what is stored (content the caller could not
    see): ``check_settings`` must not judge them again as if the caller had submitted them."""


@dataclass(frozen=True)
class SettingsProblem:
    """Something wrong with stored settings that the reader may be told: ``loc`` is the path under
    the settings, ``code`` a short lowercase code the UI words, ``message`` the English fallback."""

    loc: SettingsPath
    code: str
    message: str


@dataclass(frozen=True)
class SettingsView:
    """What ``view_settings`` answers: the settings as this reader may see them, and the problems
    this reader may be told about."""

    settings: dict[str, Any]
    problems: tuple[SettingsProblem, ...] = ()


@dataclass(frozen=True)
class RestoredSettings:
    """What ``restore_settings`` answers: the settings with what was hidden put back, and the
    paths it put back (see :attr:`SettingsContext.preserved`)."""

    settings: dict[str, Any]
    preserved: tuple[SettingsPath, ...] = ()


class Source(Protocol):
    """A producer of occurrences for a calendar it is enabled on. ``public`` sources
    are the only ones called for an anonymous read, with ``viewer=None``; the default
    for a source is not public, and a public source must return only what is public
    in its own module. An optional ``async check_settings(sctx, settings)`` may raise
    :class:`SourceSettingsError`.

    **Settings are shown to whoever manages the calendar, who may not be allowed to see all of
    what they name.** Two more optional hooks let a source keep that to itself:
    ``async view_settings(sctx, settings) -> SettingsView`` returns the settings as
    ``sctx.viewer`` may see them (a redacted copy; the default is unchanged) and the problems they
    may be told about; ``async restore_settings(sctx, submitted, stored) -> RestoredSettings``
    puts back, from ``stored``, what ``view_settings`` hid, before the settings are validated and
    stored. Both run on a connection of their own, like every plugin call."""

    id: str
    label_key: str
    public: bool
    color: str | None
    icon: str | None
    settings_model: type[BaseModel] | None

    async def occurrences(
        self, ctx: SourceContext, start: datetime, end: datetime
    ) -> Sequence[SourceOccurrence]: ...


class NoExtra(BaseModel):
    """The ``extra`` of an event type that has none."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class EventType:
    """An event type. ``extra_model`` validates the event's ``extra`` (and must forbid
    unknown keys); only ``public_fields`` ever reach a public page."""

    id: str
    label_key: str
    extra_model: type[BaseModel]
    public_fields: frozenset[str] = frozenset()
    icon: str | None = None


class SourceError(Exception):
    """Raised by a source's ``occurrences`` to say why it cannot answer: ``code`` (lowercase,
    digits and underscores, at most 32 characters) becomes the status code the console shows,
    instead of the generic ``raised``. It carries no message: put nothing private in it."""

    def __init__(self, code: str) -> None:
        if not re.fullmatch(r"[a-z0-9_]{1,32}", code):
            raise ValueError("a source error code is 1-32 of [a-z0-9_]")
        super().__init__(code)
        self.code = code


class SourceSettingsError(Exception):
    """Raised by ``check_settings`` (or ``restore_settings``); ``loc`` is the path under the entry's
    ``settings``."""

    def __init__(self, loc: tuple[str | int, ...], message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.loc = loc
        self.message = message
        self.code = code
        """A short lowercase code the UI words in the reader's language; optional."""


class SourceStatus(BaseModel):
    """How one ``(calendar, source)`` call went; only plugin sources are reported."""

    model_config = ConfigDict(frozen=True)

    id: str
    calendar_id: uuid.UUID
    status: Literal["ok", "truncated", "failed", "timeout", "skipped", "not_installed"]
    code: str | None = None
