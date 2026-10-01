"""Which stored URLs are safe to put in a page.

One definition, shared by the write path (reject on the way in) and the public
render (skip on the way out, for rows saved before the write path checked).
"""

from __future__ import annotations

from urllib.parse import urlsplit


def _clean(value: str) -> bool:
    return bool(value) and not any(ch.isspace() or ord(ch) < 32 for ch in value)


def is_http_url(value: str) -> bool:
    """An absolute ``http`` / ``https`` URL with a host and no whitespace."""
    if not _clean(value):
        return False
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def is_site_relative(value: str) -> bool:
    """A path on this site: starts with one ``/``, never ``//`` or ``/\\``
    (browsers read both as another host)."""
    if not value.startswith("/") or value.startswith(("//", "/\\")):
        return False
    return _clean(value)


def image_or_none(value: str | None) -> str | None:
    """*value* if it is an http(s) or site-relative URL, else ``None``."""
    if value and (is_http_url(value) or is_site_relative(value)):
        return value
    return None


def canonical_or_none(value: str | None) -> str | None:
    """*value* if it is an absolute http(s) URL, else ``None``."""
    return value if value and is_http_url(value) else None
