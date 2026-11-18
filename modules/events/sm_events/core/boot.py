"""Everything the public surface needs wired once the settings are known.

None of this can run while the app is being built: where the public pages mount and which
languages they mount for come from the database, and the host hydrates module settings at
*lifespan* start, so a prefix read earlier is the pydantic default whatever an operator
configured. :meth:`sm_events.module.EventsModule.on_startup` is the first moment the
answers are real, and calls :func:`wire_public`.

* the routers, one mount per language (:func:`mount_public_routers`);
* the auth exemption for ``GET`` and ``HEAD`` under each prefix (:func:`exempt_public_routes`),
  added to the live registry ``AuthMiddleware`` reads, because the prefixes are not known
  when the module registers its static routes;
* the rate limits for anonymous machine traffic (:func:`register_public_rate_limits`), added
  to the live ``app.state.rate_limit_rules`` registry the limiter reads per request.

**Idempotent.** A lifespan can run again on the same app (a test client, a reload), and a
mounted router cannot be unmounted, so the second call changes nothing: the prefix and
languages of the first stand. Both are restart-only settings.
"""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from simple_module_core.app_state import get_public_routes, get_rate_limit_rules
from simple_module_core.rate_limit import RateLimitRule

from sm_events.core import constants, locales, public_prefix, tenancy
from sm_events.core.settings import EventsSettings
from sm_events.web.endpoints.public import _urls

__all__ = [
    "dir_prefix",
    "exempt_public_routes",
    "mount_public_routers",
    "register_public_rate_limits",
    "wire_public",
]

logger = logging.getLogger(__name__)


def dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one "/"."""
    return f"{prefix.rstrip('/')}/"


def _first_segments(app: FastAPI) -> frozenset[str]:
    """The literal first path segment of every route already on the app: what another module
    mounted at the root, which a public prefix must not shadow."""
    found: set[str] = set()
    for context in iter_route_contexts(app.routes):
        first = context.path.lstrip("/").split("/", 1)[0]
        if first and "{" not in first:
            found.add(first)
    return frozenset(found)


_PREFIX_SETTINGS = ("public_route_prefix", "public_prefix")
"""The settings other modules name their public prefix by (news and pagebuilder:
``public_route_prefix``)."""


def _configured_prefixes(app: FastAPI) -> frozenset[str]:
    """First segments of the public prefixes other modules are *configured* to mount at.

    ``_first_segments`` sees only what is mounted already, and a module that mounts its router in
    its own ``on_startup`` (news does) may start after this one. Its settings are hydrated before
    any ``on_startup`` runs, so they are read here: every service container on ``app.state``
    that holds settings with one of :data:`_PREFIX_SETTINGS`, this module's own excepted."""
    found: set[str] = set()
    # Starlette's ``State`` keeps its attributes in ``_state``; a test double has ``__dict__``.
    attributes = getattr(app.state, "_state", None) or vars(app.state)
    for name, services in attributes.items():
        if name == constants.PACKAGE:
            continue
        settings = getattr(services, "settings", None)
        if isinstance(settings, EventsSettings):  # this module's own, under whatever name
            continue
        for attr in _PREFIX_SETTINGS:
            value = getattr(settings, attr, None)
            first = value.strip().strip("/").split("/", 1)[0] if isinstance(value, str) else ""
            if first:
                found.add(first)
    return frozenset(found)


def wire_public(app: FastAPI) -> str | None:
    """Publish the prefix and languages, then mount, exempt and limit. The effective
    prefix, or ``None`` when no settings were registered (nothing to read)."""
    services = getattr(app.state, constants.PACKAGE, None)
    if services is None:
        return None
    if services.public_wired is not None:
        return services.public_wired[0]
    settings = services.settings
    locales.use(*settings.content_locales)
    languages = locales.supported()
    taken = _first_segments(app) | _configured_prefixes(app) | set(languages)
    prefix = public_prefix.effective(settings.public_prefix, taken=taken)
    _urls.use(prefix)
    _urls.warn_if_unset(app, tenancy.mode_of(app))
    mount_public_routers(app, prefix)
    exempt_public_routes(app, prefix, languages)
    register_public_rate_limits(app, prefix, languages)
    services.public_wired = (prefix, languages)
    return prefix


def mount_public_routers(app: FastAPI, prefix: str) -> None:
    """One mount per language: the default at the bare prefix, every other at ``/{locale}``.
    With several languages, the default's redundant ``/{default}{prefix}`` 301s to the bare one."""
    from sm_events.web.endpoints.public import alias_router, public_router

    languages = locales.supported()
    for locale in languages:
        app.include_router(public_router(locale), prefix=f"{locales.path_prefix(locale)}{prefix}")
    if len(languages) > 1:
        app.include_router(alias_router(prefix), prefix=f"/{locales.default()}{prefix}")


def exempt_public_routes(app: FastAPI, prefix: str, languages: tuple[str, ...]) -> None:
    """Let an anonymous visitor read under each prefix, ``GET`` and ``HEAD`` only: a ``POST``
    under it still needs a session.

    The trailing slash on the prefix rule is load-bearing (these match with ``startswith``, so
    a bare ``/events`` would also exempt ``/eventsfoo``), and the bare prefix is exempt exactly:
    without it a visitor who trims the URL gets the sign-in screen, because auth runs before
    the redirect to the trailing slash.
    """
    registry = get_public_routes(app)
    if registry is None:  # no auth middleware: nothing to be exempt from
        return
    bases = [f"{locales.path_prefix(locale)}{prefix}" for locale in languages]
    if len(languages) > 1:
        bases.append(f"/{locales.default()}{prefix}")  # the redundant alias, which redirects
    for base in bases:
        registry.add_prefix(dir_prefix(base), methods=constants.PUBLIC_METHODS)
        registry.add_exact(base.rstrip("/"), methods=constants.PUBLIC_METHODS)


def _feed_pattern(base: str, *, default: bool) -> str:
    """Every ``.ics`` under ``base`` (``/x.ics``, ``/c/x.ics``), and the sitemap on the default
    language's. One path segment each, so it matches the routes and nothing nested deeper."""
    alternatives = [r"[^/]+\.ics", rf"{constants.SEGMENT_CALENDAR}/[^/]+\.ics"]
    if default:
        alternatives.append(rf"{constants.SEGMENT_SITEMAP}\.xml")
    return rf"^{re.escape(base)}/(?:{'|'.join(alternatives)})$"


def register_public_rate_limits(app: FastAPI, prefix: str, languages: tuple[str, ...]) -> None:
    """Budgets for anonymous machine traffic, per IP: the feeds and sitemap under every
    language, the public occurrences API once. Pages ride the host's ``rate_limit_public``."""
    registry = get_rate_limit_rules(app)
    if registry is None:
        return
    methods = constants.PUBLIC_METHODS
    for locale in languages:
        pattern = _feed_pattern(
            f"{locales.path_prefix(locale)}{prefix}", default=locales.is_default(locale)
        )
        registry.add_regex(pattern, RateLimitRule(constants.FEED_RATE, key="ip", methods=methods))
    registry.add_exact(
        _urls.api_path(), RateLimitRule(constants.PUBLIC_API_RATE, key="ip", methods=methods)
    )
