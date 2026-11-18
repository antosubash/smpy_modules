"""The plugin-facing surface: the only module a plugin imports from ``sm_events``.

A package that ships ``events_extensions.py`` (with ``def register(registry)``) puts
its own dates on a calendar (a :class:`Source`) and adds event types (an
:class:`EventType`). Everything it needs is here; see ``docs/writing-a-plugin.md``.
"""

from __future__ import annotations

from sm_events.calendar.extension_types import (
    EventType,
    NoExtra,
    SettingsContext,
    Source,
    SourceCalendar,
    SourceContext,
    SourceOccurrence,
    SourceSettingsError,
    SourceStatus,
    SourceViewer,
)

__all__ = [
    "EventType",
    "NoExtra",
    "SettingsContext",
    "Source",
    "SourceCalendar",
    "SourceContext",
    "SourceOccurrence",
    "SourceSettingsError",
    "SourceStatus",
    "SourceViewer",
]
