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

from sm_events.core import constants

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

    public_prefix: str = Field(default=constants.DEFAULT_PUBLIC_PREFIX, json_schema_extra=_RESTART)
    """Where the public pages, feeds and sitemap are served (for example ``/events``).
    One path of lower-case letters, digits and hyphens that no other part of the site uses;
    anything else is ignored and ``/events`` is served."""

    public_cache_seconds: int = constants.PUBLIC_CACHE_SECONDS
    """How long a browser or cache may keep a public event page, feed or sitemap, in
    seconds. ``0`` sends ``no-store``, so a change shows at once."""

    public_title: str = constants.MODULE_NAME
    """The title of the public events pages and of the all-calendars feed (``calendar.ics``):
    what the site calls its events, for example ``What's on``."""

    import_max_bytes: int = constants.IMPORT_DEFAULT_BYTES
    """The largest ``.ics`` file an import accepts, in bytes (default 5 MiB). Read per request
    and kept between 64 KiB and 20 MiB, whatever is stored here."""

    reminders_enabled: bool = True
    """Whether signed-in users can ask for a reminder before an event and the reminders are
    sent. Reminders also need a mail transport that delivers, the host's public base URL and a
    running background worker with its beat."""

    default_reminder_minutes: tuple[int, ...] = (60,)
    """How long before an event "Remind me" suggests being reminded, in minutes. Only 15, 60,
    1440 (a day) and 10080 (a week) are used; a calendar can have its own suggestion. Nobody is
    followed automatically."""

    subscription_refresh_minutes: int = 60
    """How often a subscribed calendar is fetched again, in minutes, unless a subscription sets
    its own. Read where it is used and kept between 15 and 1440, whatever is stored here."""

    allow_private_subscription_urls: bool = Field(
        default=False,
        json_schema_extra={
            # A group heading is the one thing the settings screen always shows next to a field:
            # a boolean's own description is hidden while a stored value overrides it.
            "group": (
                "Warning: with the switch below on, managers can make this server request "
                "internal addresses (see the subscriptions guide)"
            )
        },
    )
    """Lets a subscription use an address on this site's own network (private ranges such as
    10.x or 192.168.x, plain ``http://`` and any port). Never lets one reach this server's
    loopback, link-local or cloud-metadata addresses. WARNING: with this on, anyone who may
    subscribe a calendar and holds ``events.manage`` can make the server send GET requests to
    internal http(s) addresses (including services on this server's own private address). What
    they can learn is whether something reachable there answers with a calendar: a failure is
    shown only as "unreachable" or "not a calendar", never as a port, TLS or status detail. A
    system setting: only someone with
    ``settings.edit`` changes it, never a calendar owner."""
