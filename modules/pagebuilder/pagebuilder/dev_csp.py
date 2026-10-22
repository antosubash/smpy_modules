"""Let the editor's bundled font load from the Vite dev server (#188).

The editor's Inter is self-hosted: ``@fontsource-variable/inter`` is part of
the bundle, so in production its files are served from the host's own origin
and the console's ``font-src 'self'`` already allows them. Under ``vite dev``
every bundled asset comes from the Vite origin instead, and the framework's
development CSP widens ``script-src``, ``style-src`` and ``connect-src`` for
that origin but not ``font-src`` — so a module that ships a font file is
blocked in development only.

This provider adds the Vite origin to ``font-src`` in development and nothing
otherwise; the production policy is unchanged. It belongs in the framework's
``dev_csp`` and can go once that widens ``font-src`` itself.

A copy of ``news.dev_csp``: the two modules do not depend on each other, and
either one alone needs it. Change them together.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

# A concrete DNS name (or IPv4 address): dot-separated labels, no wildcard.
_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")
_IPV6 = re.compile(r"[0-9a-f:.]+")


def vite_origin(raw: object) -> str | None:
    """The ``scheme://host[:port]`` of a configured dev URL, or ``None``.

    Strict on purpose: the value is a setting, and the framework's own source
    check accepts a bare scheme (``https:``) or a wildcard host, either of
    which would turn "the dev server" into "anywhere". Only http(s), a
    concrete host and an optional port pass; credentials, a path beyond ``/``,
    a query or a fragment are refused rather than stripped.
    """
    value = str(raw or "").strip()
    if not value or "*" in value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if "@" in parts.netloc or parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    host = (parts.hostname or "").lower()
    if _HOSTNAME.fullmatch(host):
        netloc = host
    elif ":" in host and _IPV6.fullmatch(host):
        netloc = f"[{host}]"
    else:
        return None
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parts.scheme.lower()}://{netloc}"


def vite_font_source(app: Any) -> Iterable[tuple[str, str]]:
    """``[("font-src", <vite origin>)]`` under the Vite dev server, else ``[]``."""
    sm = getattr(app.state, "sm", None)
    config = getattr(sm, "inertia_config", None)
    if config is None or getattr(config, "environment", None) != "development":
        return []
    origin = vite_origin(getattr(config, "dev_url", None))
    return [("font-src", origin)] if origin else []
