"""The one rule for "a URL a browser may be sent to": absolute, ``http`` or ``https``, with a
host and no credentials. Used for a stored event's links and for a plugin's."""

from __future__ import annotations

from urllib.parse import urlsplit

from sm_events.core import constants

__all__ = ["is_site_image", "is_web_url", "site_origin_of"]


def is_web_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        has_credentials = (
            parts.username is not None or parts.password is not None or "@" in parts.netloc
        )
    except ValueError:
        return False
    return (
        parts.scheme.lower() in constants.WEB_URL_SCHEMES
        and bool(parts.hostname)
        and not has_credentials
    )


def _origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    default = {"http": 80, "https": 443}.get(parts.scheme.lower())
    return parts.scheme.lower(), parts.hostname.lower(), None if port in (None, default) else port


def site_origin_of(value: str) -> tuple[str, str, int | None] | None:
    """``(scheme, host, port)`` of an absolute address (the default port left out), or ``None``."""
    return _origin(value)


def is_site_image(value: str, origin: str = "") -> bool:
    """Whether the site's own page policy (``img-src 'self'``) lets a page load ``value``: a path
    on the site (one leading ``/``, no scheme, no ``//``, no backslash, no whitespace or control
    character), or, when ``origin`` is known, an http(s) address on that same origin. Everything
    else is off-site and is never emitted."""
    if not value or len(value) > constants.URL_MAX:
        return False
    if value.startswith("/"):
        return (
            not value.startswith("//")
            and "\\" not in value
            and not any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)
        )
    if not origin or not is_web_url(value):
        return False
    return _origin(value) == _origin(origin)
