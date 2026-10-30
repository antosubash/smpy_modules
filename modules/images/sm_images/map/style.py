"""The map's basemap: the ``map_style_url`` setting's rule and its CSP origin.

The map draws a MapLibre style fetched by the viewer's browser, and that style
pulls its tiles, glyphs and sprite from the same host (OpenFreeMap's do). The
host's Content-Security-Policy would block every one of those requests, so the
module declares the style's origin through a CSP *provider*: evaluated per
response from the hydrated settings, so a Settings-screen edit applies at the
next page load, no restart. A style that pulls from a second host needs that
host on the same origin, or a CDN in front of both - only the style's own
origin is allowed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from sm_images.core import constants

__all__ = ["DEFAULT_STYLE_URL", "csp_sources", "style_origin", "validate_style_url"]

DEFAULT_STYLE_URL = "https://tiles.openfreemap.org/styles/positron"

# connect-src: the style JSON, TileJSON, vector tiles, glyphs and sprite are all
# fetched. img-src: raster tiles and sprite sheets, which some builds load as images.
_DIRECTIVES = ("connect-src", "img-src")


def validate_style_url(value: str) -> str:
    """Empty, or an absolute ``https://`` URL with a host and no whitespace."""
    value = value.strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError for a non-numeric / out-of-range port
    except ValueError:
        raise ValueError("must be empty or an https:// URL") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError("must be empty or an https:// URL")
    return value


def style_origin(url: str) -> str | None:
    """``https://host[:port]`` of a style URL, or ``None`` when there is none."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:  # a stored value that predates validation must not 500 every response
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"https://{host}{port}"


def csp_sources(app: Any) -> Iterable[tuple[str, str]]:
    """The CSP provider: the configured style's origin, for every fetch it makes."""
    services = getattr(app.state, constants.PACKAGE, None)
    settings = getattr(services, "settings", None)
    origin = style_origin(getattr(settings, "map_style_url", "") or "")
    return [(directive, origin) for directive in _DIRECTIVES] if origin else []
