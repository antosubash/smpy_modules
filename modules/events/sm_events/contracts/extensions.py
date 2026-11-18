"""The plugin-facing surface: the only module a plugin imports from ``sm_events``.

A package that ships ``events_extensions.py`` (with ``def register(registry)``) puts
its own dates on a calendar (a :class:`Source`) and adds event types (an
:class:`EventType`). ``registry`` is a :class:`Registrar`: ``add_source`` and
``add_type`` only, ids namespaced ``<entry-point name>:<name>``. Everything a plugin
needs is here.

**Settings are not secret.** A source's ``settings_model`` is stored in the clear on the
calendar and
shown to whoever manages it, so registration refuses a model with a ``SecretStr``/``SecretBytes``
or sealed-secret field: keep secrets in your own module's settings and name them here.
See ``docs/extensions.md``.
"""

from __future__ import annotations

from sm_events.calendar.plugins.extension_types import (
    EventType,
    NoExtra,
    SettingsContext,
    Source,
    SourceCalendar,
    SourceContext,
    SourceError,
    SourceOccurrence,
    SourceSettingsError,
    SourceStatus,
    SourceViewer,
)
from sm_events.calendar.plugins.extensions import Registrar
from sm_events.calendar.plugins.registry import RegistryFrozenError
from sm_events.core import constants

ITEM_MAX_DAYS = constants.MAX_EVENT_DAYS
"""The longest an item may run, in days: a longer one is refused, so clip it."""
ITEM_TITLE_MAX = constants.SOURCE_TITLE_MAX
"""The longest an item title, in characters."""

__all__ = [
    "ITEM_MAX_DAYS",
    "ITEM_TITLE_MAX",
    "EventType",
    "NoExtra",
    "Registrar",
    "RegistryFrozenError",
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
