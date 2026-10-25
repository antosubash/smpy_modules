"""Wiring the anonymous read surface, once the settings are the real ones.

Modelled on :mod:`pagebuilder.boot`, for the same reason and with the same
consequence. ``public_route_prefix`` is a database-backed setting (there are
no ``SM_RECORDS_*`` environment variables), and the host hydrates a module's
settings at *lifespan start* — after ``register_routes`` and
``register_public_routes`` have both already run. Reading the prefix in either
of those hooks would read the pydantic default and mount the public API at an
address the operator did not choose.

So both halves run from ``on_startup`` instead. That is late for mounting
routes, and it works for two reasons this module depends on:

* ``app.include_router`` before the first request is indistinguishable from
  including it at build time — the router table is consulted per request.
* the public-route registry is published on ``app.state.public_routes`` and
  read live by ``AuthMiddleware``, so a prefix added now is exempt from the
  next request onward.

The cost is that changing the prefix needs a restart, which is exactly what
``requires_restart`` on the field tells the operator (``settings.py``).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI

from sm_records import constants
from sm_records.settings import RecordsSettings
from sm_records.settings_checks import DEFAULT_PUBLIC_ROUTE_PREFIX, check_public_route_prefix

logger = logging.getLogger(__name__)

_PREFIX_KIND = "prefix"
"""``PublicRoute.kind`` for the rule this module registers — named so the
idempotence check below compares against the same word ``add_prefix`` uses."""


def public_prefix(settings: RecordsSettings) -> str:
    """The prefix to mount at, with a bad stored value demoted to a log line.

    ``RecordsSettings`` refuses a prefix that would exempt the admin surface
    (:func:`~sm_records.settings_checks.check_public_route_prefix`), so an operator
    cannot save one. A row written before that rule existed can still reach
    here, and ``on_startup`` is the wrong place to discover it: raising takes
    the whole host down, and the only way to correct the setting is the
    Settings screen inside the app that will not start. So the default is
    used instead, loudly — the anonymous API moves, and everything else keeps
    working.
    """
    try:
        return check_public_route_prefix(settings.public_route_prefix)
    except ValueError as exc:
        logger.error(
            "records: stored public_route_prefix %r is invalid (%s); falling back to %r. "
            "Fix it on the Settings screen — the anonymous read API is mounted at the "
            "fallback until you do.",
            settings.public_route_prefix,
            exc,
            DEFAULT_PUBLIC_ROUTE_PREFIX,
        )
        return DEFAULT_PUBLIC_ROUTE_PREFIX


def dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one ``/``.

    Public-route rules match with ``str.startswith``, so an unterminated
    prefix leaks into every sibling path that merely shares its first
    characters. The default here makes that concrete: ``/api/records/public``
    without the trailing slash would also match ``/api/records/publicfoo``,
    and a prefix an operator shortened to ``/api/records`` would hand the
    entire admin API to anonymous callers.
    """
    return f"{prefix.rstrip('/')}/"


def exempt_public_routes(app: FastAPI, settings: RecordsSettings) -> None:
    """Exempt the anonymous read API from ``AuthMiddleware``.

    Without it the routes mount and every request to them 302s to the login
    screen, which is the whole of what ``is_public`` is supposed to mean.
    Pinned to ``PUBLIC_ROUTE_METHODS`` (``GET``/``HEAD``) so a future route
    added under the same prefix cannot widen the exemption by accident — and
    so a ``POST`` under it stays gated whatever anyone mounts there.
    """
    registry = getattr(app.state, "public_routes", None)
    if registry is None:
        # A bare test app, or a host that mounts no auth middleware. Nothing
        # is gating these paths in that case, so there is nothing to exempt.
        return
    prefix = dir_prefix(public_prefix(settings))
    methods = set(constants.PUBLIC_ROUTE_METHODS)
    # Idempotent, because ``on_startup`` is not guaranteed to run once: a host
    # that restarts the lifespan in-process would otherwise grow one identical
    # rule per restart. Matching is ``any(...)``, so duplicates are harmless
    # today and are only ever cost and noise.
    if any(
        rule.pattern == prefix and rule.kind == _PREFIX_KIND and rule.methods == frozenset(methods)
        for rule in registry.routes
    ):
        return
    registry.add_prefix(prefix, methods=methods)


def mount_public_router(app: FastAPI, settings: RecordsSettings) -> None:
    """Mount the two read routes at the configured prefix.

    At the host root rather than under the module's ``route_prefix``: the
    admin API's prefix is fixed at construction and the public one is not, and
    §10 wants the anonymous surface at an address the operator controls.
    """
    from sm_records.endpoints.api.public import router

    app.include_router(router, prefix=dir_prefix(public_prefix(settings)).rstrip("/"))


def mount_submission_views(app: FastAPI) -> None:
    """The newsletter's landing pages (#101), at the app root: their prefix
    is fixed, but outside ``view_prefix`` — the router ``register_routes``
    gets is hard-prefixed with ``/admin/records``. Idempotent, like the
    exemption above."""
    from sm_records.endpoints.public_submissions_views import router

    prefix = constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX.rstrip("/")
    if any(getattr(route, "path", "").startswith(prefix + "/") for route in app.router.routes):
        return
    app.include_router(router, prefix=prefix)


async def startup(module: Any, app: FastAPI) -> None:
    """:meth:`RecordsModule.on_startup`'s body — moved here for the 300-line cap.

    Hands the health check what it cannot reach on its own.
    ``register_health_checks`` runs before the lifespan opens the database, and
    module settings are hydrated from the DB at lifespan start — so the check
    closes over the *module instance* and reads both from there, once they
    exist. Storing them rather than capturing ``app`` keeps the check free of
    the request/app object entirely, which is what lets a test call it with a
    module whose ``db`` is a bare ``DatabaseState``.

    ``module.settings`` is overwritten with the hydrated object: it was either
    ``None`` or a test's pre-seeded stand-in until now, and the check wants
    ``reindex_stale_after_seconds`` as the operator set it.
    """
    module.db = getattr(app.state, "sm", None) and app.state.sm.db
    from sm_records import tenancy

    # Single or multi, from the built stack (tenancy §A.3); the health check
    # and the sidebar read it from here (§A.5, §I).
    module.tenancy_mode = tenancy.configure(app)
    if (session_class := getattr(module.db, "sync_session_class", None)) is not None:
        tenancy.install_guard(session_class)  # before any read below (tenancy §A.4)
    services = getattr(app.state, constants.PACKAGE, None)
    if services is not None and getattr(services, "settings", None) is not None:
        module.settings = services.settings

    # The anonymous read API (design §10), mounted and exempted here for the
    # reason in this module's docstring: its prefix is a DB-backed setting
    # that only exists as the operator set it from this point on.
    settings = module.settings or RecordsSettings()
    mount_public_router(app, settings)
    exempt_public_routes(app, settings)
    mount_submission_views(app)
    # The media library the ``media`` picker calls, found by route shape
    # (never by importing it) — :mod:`sm_records.media`. Same reason as above.
    from sm_records import media

    media.configure(app, settings.media_api_prefix)

    # Dropping a content locale is not refused at save (``settings_checks``
    # says why), so this is what makes the records left behind visible. Once
    # per boot: the framework offers no hook to re-run it when an operator
    # hydrates new settings, which the health check's docstring records.
    from sm_records import health

    if module.db is not None:
        module.orphaned_locales = await health.count_orphaned_locales(module.db, settings)

    # The first sidebar read: ``register_menu_items`` ran before there was a
    # database, so until now the registry holds the hub entry and none of the
    # per-type ones. Forced past the refresh window because there is nothing
    # to be stale yet — and deliberately last, so a database this cannot read
    # costs a log line rather than a boot.
    from sm_records import menu

    await menu.refresh(module, force=True)
