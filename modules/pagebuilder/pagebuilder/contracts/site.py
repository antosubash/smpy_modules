"""What the site is configured to publish: content languages and the public CSP (#336).

Another module asks these instead of reading ``app.state.pagebuilder`` or
importing ``pagebuilder.core``, so pagebuilder's settings field names and its
``app.state`` attribute stay its own.

Two ways to ask about languages, for two moments:

- :func:`content_locales` reads the settings the *host* hydrated onto ``app``,
  and is the one to call from another module's ``on_startup``. Module startup
  hooks run in registration order, so pagebuilder's own ``on_startup`` (which
  publishes the process-wide instance) may not have run yet; hydration has.
- :func:`supported`, :func:`default`, :func:`is_default`, :func:`resolve` and
  :func:`path_prefix` read that process-wide instance, for code with no app
  (a model default, a URL builder), once startup is done.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from pagebuilder.core.locales import default, is_default, path_prefix, resolve, supported

__all__ = [
    "ContentLocales",
    "content_locales",
    "default",
    "is_default",
    "path_prefix",
    "public_csp",
    "resolve",
    "supported",
]


class ContentLocales(NamedTuple):
    locales: tuple[str, ...]
    """Every language a page may be authored in, default first."""
    default: str
    """The one served at the unprefixed public URL."""


def _settings(app: Any) -> Any | None:
    """Pagebuilder's hydrated settings on ``app``; ``None`` when it is not mounted."""
    services = getattr(getattr(app, "state", None), "pagebuilder", None)
    return getattr(services, "settings", None)


def content_locales(app: Any) -> ContentLocales | None:
    """The content languages as the host hydrated them onto ``app``.

    ``None`` where pagebuilder is not mounted, or has not registered its
    settings container.
    """
    settings = _settings(app)
    if settings is None:
        return None
    return ContentLocales(tuple(settings.content_locales), settings.default_content_locale)


def public_csp(app: Any) -> str | None:
    """The ``Content-Security-Policy`` pagebuilder sends on public pages.

    ``None`` when pagebuilder is not mounted on ``app`` or sets no policy
    (an empty or blank ``public_csp``).
    """
    csp = getattr(_settings(app), "public_csp", None)
    return csp if isinstance(csp, str) and csp.strip() else None
