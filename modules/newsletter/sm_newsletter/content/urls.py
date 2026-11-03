"""URL rules for email content: what a link or image may point at."""

from __future__ import annotations

from urllib.parse import urlsplit

UNSUBSCRIBE_TAG = "{{unsubscribe_url}}"
MAX_URL = 2000


def _plain(value: str) -> bool:
    return len(value) <= MAX_URL and not any(
        ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value
    )


def _http(value: str) -> bool:
    lowered = value.lower()
    if not (lowered.startswith(("http://", "https://"))):
        return False
    try:
        return bool(urlsplit(value).hostname)
    except ValueError:
        return False


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


def is_relative(url: str) -> bool:
    """True when the URL still needs a host (a site path or protocol-relative)."""
    return url.startswith("/")


def absolute(base: str, url: str) -> str:
    """Make ``url`` absolute against ``base``; absolute, mailto and the tag pass through."""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/") and base:
        return base.rstrip("/") + url
    return url
