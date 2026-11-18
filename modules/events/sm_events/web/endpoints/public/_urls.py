"""Where the public surface lives: path builders, the origin and absolute URLs.

The prefix is the stored ``public_prefix`` setting, normalised and published once at
startup (:func:`use`), because these are pure functions with no request to read
``app.state`` from. Before startup it is ``/events``. The default content locale serves at
the bare prefix and every other at ``/{locale}{prefix}``
(:func:`sm_events.core.locales.path_prefix`).

**The origin.** Events has no setting of its own for it: on a single-tenant host it is the
host's ``public_base_url``; on a multi-tenant host each organisation's site is its own
host, so there is none to configure. While none is configured, absolute URLs come from the
request's ``Host`` header, which the client chooses, so a cache must key on it
(:func:`guessed`, and ``_cache.apply`` adds ``Host`` to ``Vary``) and :func:`warn_if_unset`
says so at startup in production.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from urllib.parse import quote

from fastapi import Request
from simple_module_core.environments import NON_PROD_ENVIRONMENTS
from sm_events.core import constants, locales
from sm_events.core.tenancy import TenancyMode, mode_of

__all__ = [
    "absolute",
    "api_path",
    "calendar_ics_path",
    "calendar_path",
    "configured_origin",
    "event_ics_path",
    "event_path",
    "guessed",
    "index_path",
    "prefix",
    "public_base_url",
    "sitemap_path",
    "use",
    "warn_if_unset",
]

_log = logging.getLogger("sm_events.public")

_prefix: str = constants.DEFAULT_PUBLIC_PREFIX


def use(value: str) -> None:
    """Publish the effective public prefix (leading slash, none trailing)."""
    global _prefix
    _prefix = value


def prefix() -> str:
    return _prefix


def _base(locale: str) -> str:
    return f"{locales.path_prefix(locale)}{_prefix}"


def _segment(slug: str) -> str:
    return quote(slug, safe="")


def index_path(locale: str) -> str:
    """The upcoming list: ``/events/`` (``/de/events/``)."""
    return f"{_base(locale)}/"


def calendar_path(slug: str, locale: str) -> str:
    return f"{_base(locale)}/{constants.SEGMENT_CALENDAR}/{_segment(slug)}"


def event_path(slug: str, locale: str, date: date | None = None) -> str:
    """An event's page; ``date`` names one occurrence of a series (``?date=``)."""
    path = f"{_base(locale)}/{_segment(slug)}"
    return path if date is None else f"{path}?date={date.isoformat()}"


def event_ics_path(slug: str, locale: str) -> str:
    return f"{_base(locale)}/{_segment(slug)}.ics"


def calendar_ics_path(slug: str | None, locale: str) -> str:
    """One calendar's feed, or every public calendar's when ``slug`` is ``None``."""
    if slug is None:
        return f"{_base(locale)}/{constants.SEGMENT_CALENDAR_FEED}.ics"
    return f"{_base(locale)}/{constants.SEGMENT_CALENDAR}/{_segment(slug)}.ics"


def sitemap_path() -> str:
    """One sitemap for the whole site, on the default language's prefix."""
    return f"{_prefix}/{constants.SEGMENT_SITEMAP}.xml"


def api_path() -> str:
    return f"{_prefix}/{constants.SEGMENT_API}/occurrences"


def _host_settings(app: Any) -> Any:
    return getattr(getattr(app.state, "sm", None), "settings", None)


def configured_origin(app: Any) -> str:
    """The host's ``public_base_url`` on a single-tenant host, else ``""``."""
    if mode_of(app) is not TenancyMode.SINGLE:
        return ""
    return str(getattr(_host_settings(app), "public_base_url", "") or "").strip().rstrip("/")


def guessed(app: Any) -> bool:
    """True while absolute URLs come from the request's ``Host`` header."""
    return not configured_origin(app)


def public_base_url(request: Request) -> str:
    """The origin absolute URLs use, without a trailing slash: the configured one, else
    the request's own (local development, and a multi-tenant host)."""
    return configured_origin(request.app) or f"{request.url.scheme}://{request.url.netloc}".rstrip(
        "/"
    )


def absolute(request: Request, path: str) -> str:
    """An origin-qualified URL for a path built here."""
    return f"{public_base_url(request)}{path}"


def warn_if_unset(app: Any, mode: TenancyMode) -> bool:
    """Log once at startup when a production single-tenant host has no ``public_base_url``;
    returns whether it warned. Not on a multi-tenant host, where blank is right, nor in
    development or testing."""
    environment = getattr(_host_settings(app), "environment", None)
    if not guessed(app) or environment in NON_PROD_ENVIRONMENTS:
        return False
    if mode is not TenancyMode.SINGLE:
        return False
    _log.warning(
        "events: the host's public_base_url is not set, so canonical, og:url, feed and "
        "sitemap links are built from each request's Host header, which the client "
        "chooses. Set it on the Settings screen (e.g. https://example.com); until then "
        "public responses vary on Host"
    )
    return True
