"""The languages an article can be written in, as pagebuilder sees them.

The seam, not the answer: :mod:`news.core.locales` is what the rest of this module
asks, and it borrows from here only where pagebuilder is installed. On a host
that runs both, offering a language pagebuilder did not would mean two lists to
keep in step — an article and a page are documents on the same site.

Every import is deferred into the function that needs it, for the same reason
they are in :mod:`news.integrations.pagebuilder`: this module is reachable from
``news.models``, and a module-scope import would make news — and its migrations
— unloadable without the optional ``pagebuilder`` extra. ``test_integrations``
asserts it.

A sibling of :mod:`news.integrations.pagebuilder` rather than part of it,
because these are the only functions behind the seam that answer a question
about configuration rather than about data. Everything goes through
``pagebuilder.contracts.site`` (#336), never ``pagebuilder.core`` or
``app.state.pagebuilder``.
"""

from __future__ import annotations

from typing import Any


def hydrated_locales(app: Any) -> tuple[tuple[str, ...], str] | None:
    """Pagebuilder's content locales as the *host* has just hydrated them.

    ``None`` where pagebuilder is not installed, or is not mounted on ``app``.

    ``site.content_locales(app)`` rather than the functions below, and only at
    startup. Those go via pagebuilder's process-global, which that module
    republishes from its own ``on_startup`` — and module startup hooks run in
    registration order, which no longer puts news after pagebuilder now that it
    does not depend on it. Asking too early would mount the news viewer for
    pagebuilder's *pre-hydration* languages and 404 every translated article on
    a site that configured a second one. The hydrate step, by contrast, has
    finished before any ``on_startup`` runs.
    """
    try:
        from pagebuilder.contracts import site
    except ImportError:
        return None
    found = site.content_locales(app)
    return None if found is None else (found.locales, found.default)


def content_locales() -> tuple[str, ...]:
    """Every language a page — and so an article — may be authored in."""
    from pagebuilder.contracts import site

    return site.supported()


def default_locale() -> str:
    """The language that serves at the unprefixed public URL."""
    from pagebuilder.contracts import site

    return site.default()


def is_default_locale(locale: str) -> bool:
    from pagebuilder.contracts import site

    return site.is_default(locale)


def resolve_locale(value: str | None) -> str | None:
    """``value`` as a configured content locale, or ``None`` if it is not one."""
    from pagebuilder.contracts import site

    return site.resolve(value)


def locale_path_prefix(locale: str) -> str:
    """The URL segment a language contributes — ``""`` for the default one."""
    from pagebuilder.contracts import site

    return site.path_prefix(locale)
