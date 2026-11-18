"""The one rule for "a URL a browser may be sent to": absolute, ``http`` or ``https``, with a
host and no credentials. Used for a stored event's links and for a plugin's."""

from __future__ import annotations

from urllib.parse import urlsplit

from sm_events.core import constants

__all__ = ["is_web_url"]


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
