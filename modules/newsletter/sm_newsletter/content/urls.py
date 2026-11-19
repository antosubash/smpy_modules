"""URL rules for email content: what a link or image may point at."""

from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

UNSUBSCRIBE_TAG = "{{unsubscribe_url}}"
# The tracking placeholders in a snapshot (``tracking.rewrite`` writes them).
PIXEL_TAG = "{{open_pixel}}"
LINK_PREFIX = "{{link:"
MAX_URL = 2000


def _plain(value: str) -> bool:
    """No whitespace, control (Cc) or format (Cf: RLO, ZWSP, BOM) characters."""
    return len(value) <= MAX_URL and not any(
        ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf") for ch in value
    )


def _http(value: str) -> bool:
    lowered = value.lower()
    if not (lowered.startswith(("http://", "https://"))):
        return False
    try:
        return bool(urlsplit(value).hostname)
    except ValueError:
        return False


def is_http_link(value: str) -> bool:
    """A plain ``http(s)://`` URL with a host: what click tracking may rewrite."""
    return _plain(value) and _http(value)


def check_link(value: str) -> str:
    """http(s) with a host, ``mailto:``, a site path, or exactly the unsubscribe tag."""
    if value == UNSUBSCRIBE_TAG:
        return value
    if not _plain(value) or "{{" in value or "\\" in value:
        raise ValueError("not an allowed link")
    if _http(value):
        return value
    if value.lower().startswith("mailto:") and len(value) > len("mailto:"):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    raise ValueError("not an allowed link")


def check_image(value: str) -> str:
    """Empty, http(s), protocol-relative with a host, or a site path."""
    if value == "":
        return value
    if not _plain(value) or "{{" in value or "\\" in value:
        raise ValueError("not an allowed image address")
    if _http(value):
        return value
    if value.startswith("//") and _http("https:" + value):
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    raise ValueError("not an allowed image address")


def is_site_path(value: str) -> bool:
    """A path on the site itself: one leading ``/``, no scheme, no ``//``, no backslash, no
    whitespace, control or format character, no merge tag, at most :data:`MAX_URL` long. What an
    event card's snapshot always holds, and the only thing the card may link to."""
    return (
        _plain(value)
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and "{{" not in value
    )


def check_site_path(value: str) -> str:
    if not is_site_path(value):
        raise ValueError("not a path on this site")
    return value


def check_site_image(value: str) -> str:
    """Empty, or a path on the site itself."""
    return value if value == "" else check_site_path(value)


def absolute(base: str, url: str) -> str:
    """Make ``url`` absolute against ``base``; absolute, mailto and the tag pass through."""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/") and base:
        return base.rstrip("/") + url
    return url
