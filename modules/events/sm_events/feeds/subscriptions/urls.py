"""The subscription address as a secret: sealed for storage, masked for everything else.

A private calendar link (Google's "secret address", Outlook's published links) carries a bearer
token in its path or query, so the address is the credential. It is stored only as ``enc:v2:``
ciphertext (``sm_events.core.crypto``) next to a masked form, ``scheme://host[:port]/…``, which
is all the API, the console and the logs ever carry. A stored value that does not open fails
closed: there is no path on which a bad prefix or an empty value is used as the address.
"""

from __future__ import annotations

import contextlib
import ipaddress

import httpx

from sm_events.core import constants, crypto
from sm_events.core.errors_subscriptions import SecretUnreadable

__all__ = ["UrlUnreadable", "display_of", "seal", "unseal"]

_FIELD = "url"


class UrlUnreadable(SecretUnreadable):
    """The stored address does not open under any known key (or is not sealed at all)."""


def seal(url: str) -> str:
    """``url`` as ``enc:v2:`` ciphertext, ready for ``events_subscription.url_enc``."""
    return crypto.encrypt_value(url)


def unseal(stored: str) -> str:
    """The address held by ``stored``.

    Raises :class:`UrlUnreadable` for an empty value (a deleted row), for a value without an
    ``enc:`` prefix (never used as plaintext) and for one no key opens. A missing
    ``SM_SECRET_KEY`` or a malformed ``SM_SECRET_KEY_PREVIOUS`` is the operator's problem and
    raises ``RuntimeError``, whose message names the variable and never a value.
    """
    if not stored or not crypto.is_encrypted(stored):
        raise UrlUnreadable
    try:
        return crypto.decrypt_value(stored, _FIELD)
    except SecretUnreadable:
        raise UrlUnreadable from None


def host_of(url: str) -> str:
    """The lower-case IDNA host of ``url`` (what the per-host floor groups by; it is already part
    of the masked display)."""
    host = httpx.URL(url).raw_host.decode("ascii").lower().rstrip(".")
    with contextlib.suppress(ValueError):  # an IP literal in any spelling is one key
        host = str(ipaddress.ip_address(host.strip("[]")))
    return host[: constants.URL_HOST_MAX]


def display_of(url: str) -> str:
    """``scheme://host[:port]/…`` of ``url``: host as IDNA ASCII, port only when it is not the
    scheme's default, never a path, query, fragment or credential."""
    parsed = httpx.URL(url)
    host = parsed.raw_host.decode("ascii").lower()
    if ":" in host:  # an IPv6 literal
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{port}/…"
