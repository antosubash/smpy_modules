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

from fastapi import FastAPI

from sm_records import constants
from sm_records.settings import RecordsSettings


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
    registry.add_prefix(
        dir_prefix(settings.public_route_prefix), methods=set(constants.PUBLIC_ROUTE_METHODS)
    )


def mount_public_router(app: FastAPI, settings: RecordsSettings) -> None:
    """Mount the two read routes at the configured prefix.

    At the host root rather than under the module's ``route_prefix``: the
    admin API's prefix is fixed at construction and the public one is not, and
    §10 wants the anonymous surface at an address the operator controls.
    """
    from sm_records.endpoints.api.public import router

    app.include_router(router, prefix=dir_prefix(settings.public_route_prefix).rstrip("/"))
