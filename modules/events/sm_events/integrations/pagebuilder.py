"""Pagebuilder's site 404, for hosts that run it.

A visitor who follows a dead event link should land on the site's own 404 (its header,
footer, branding and design pack, in the address's language) rather than on events' plain
one. That page is pagebuilder's, and this is the one way in: ``pagebuilder.contracts.public``
and nothing deeper (its tables, settings and view code are its own to change).

Events gains no pagebuilder dependency or extra. The import is deferred into the call and
every absence answers ``None``, so the caller renders its own page: pagebuilder not
installed, installed but not mounted on this app, or older than the contract.
"""

from __future__ import annotations

from functools import cache
from importlib.util import find_spec
from typing import Any

__all__ = ["available", "render_not_found"]


@cache
def available() -> bool:
    """Whether ``simple_module_pagebuilder`` is installed in this host. Asked without
    importing it, so loading events never loads pagebuilder as a side effect."""
    try:
        return find_spec("pagebuilder") is not None
    except (ImportError, ValueError):  # a broken or half-removed distribution
        return False


def _public() -> Any:
    if not available():
        return None
    try:
        from pagebuilder.contracts import public
    except ImportError:  # older than the contract
        return None
    return public


async def render_not_found(
    request: Any,
    inertia: Any,
    db: Any,
    *,
    locale: str,
    tenant_id: str | None,
    detail: str,
) -> Any:
    """The site's 404, or ``None`` when there is no site frame to put it in.

    ``tenant_id`` is the tenant the request's own binder resolved (``None``: no layout, no
    query), never anything the client sent."""
    public = _public()
    if public is None:
        return None
    return await public.render_not_found(
        request, inertia, db, locale=locale, tenant_id=tenant_id, detail=detail
    )
