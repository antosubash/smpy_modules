"""Events settings - stored in the database, not read from the environment.

:class:`~simple_module_core.settings_base.DbBackedSettings` drops every source
pydantic-settings would consult, so there is no ``SM_EVENTS_*`` variable.
Configure them on the Settings screen (or headlessly with
``scripts/set_setting.py``). SYSTEM scope: one configuration for the whole
deployment.

There are no validators on purpose: a class that does not construct is replaced
with *all* defaults, so one bad stored value would reset every field. A stored
timezone the host does not know is handled where it is read
(:func:`sm_events.core.timezones.effective`).
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from simple_module_core.settings_base import DbBackedSettings

__all__ = ["EventsSettings"]

_RESTART: Final[dict[str, Any]] = {"requires_restart": True}
"""Marks a field the module reads once, while booting."""


class EventsSettings(DbBackedSettings):
    # ``use_attribute_docstrings`` puts the prose under each field on the
    # Settings screen: the admin UI renders ``FieldInfo.description``.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    default_timezone: str = "UTC"
    """IANA timezone (such as ``Europe/Vienna``) a new calendar starts with.
    An unknown name falls back to UTC."""

    content_locales: tuple[str, ...] = Field(default=("en",), json_schema_extra=_RESTART)
    """Languages events can be published in; the first is the default language."""
