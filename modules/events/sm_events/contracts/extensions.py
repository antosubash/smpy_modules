"""The plugin-facing surface: the only module a plugin imports from ``sm_events``.

A package that ships ``events_extensions.py`` (with ``def register(registry)``) puts
its own dates on a calendar (a :class:`Source`) and adds event types (an
:class:`EventType`). ``registry`` is a :class:`Registrar`: ``add_source`` and
``add_type`` only, ids namespaced ``<entry-point name>:<name>``. Everything a plugin
needs is here; see ``docs/writing-a-plugin.md``.
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
from sm_events.calendar.extensions import Registrar
from sm_events.calendar.registry import RegistryFrozenError

__all__ = [
    "EventType",
    "NoExtra",
    "Registrar",
    "RegistryFrozenError",
    "SettingsContext",
    "Source",
    "SourceCalendar",
    "SourceContext",
    "SourceOccurrence",
    "SourceSettingsError",
    "SourceStatus",
    "SourceViewer",
]
