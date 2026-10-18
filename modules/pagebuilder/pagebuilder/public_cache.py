"""ETag and cache headers for the public page viewer (#94).

A published page's HTML is not a function of the page alone. The chrome is
rendered in the visitor's UI language (the ``locale`` cookie, else
``Accept-Language``), and a signed-in visitor's response carries their
``auth.user`` record and a header that greets them instead of showing the CTA.
So two visitors on one URL can be owed different bytes, and the headers have to
say so:

* **Signed in** → ``private, no-cache``. No shared cache may store it, and the
  browser revalidates every time, so signing out (or in as someone else) is
  seen on the next load rather than a minute later.
* **Anonymous** → ``public`` with the configured ``max-age`` and
  ``stale-while-revalidate``, as before.
* ``Vary`` names ``Cookie`` and ``Accept-Language``: a cache must not answer a
  visitor who switched language, or signed in, from an entry stored for one who
  had not.
* The ETag digests the viewer too (UI language + who is signed in), so a
  revalidation can only 304 against a response built for the same viewer.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import Request

from pagebuilder.settings import PagebuilderSettings

VARY = "X-Inertia, Cookie, Accept-Language"
SIGNED_IN_CACHE_CONTROL = "private, no-cache"


def etag_for(
    page_id: int,
    updated_at: datetime | None,
    layout_updated_at: datetime | None = None,
    variant: str = "html",
    nav: str = "",
    viewer: str = "",
) -> str:
    """Stable, short ETag derived from page identity + last-modified time.

    ``layout_updated_at`` participates so a site-wide header / footer
    edit invalidates every page's cached chrome — without it, clients
    keep serving stale layout from cache until the page itself changes.

    The *content* locale needs no place in the digest: a page belongs to exactly
    one language, so ``page_id`` already names it. The *UI* locale does, and
    is part of ``viewer``.

    ``variant`` names the representation ("html" or "inertia"): one URL answers
    with a full page or Inertia's JSON, and a shared tag lets a browser holding
    the page get a 304 for the JSON request and hand Inertia cached HTML.

    ``nav`` is the serialised :func:`pagebuilder.site_nav.site_nav` list. Flagging,
    renaming or publishing *another* page changes this page's chrome while neither
    its own ``updated_at`` nor the layout's moves.

    ``viewer`` is :func:`viewer_key` — whose response this is.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    layout_stamp = layout_updated_at.isoformat() if layout_updated_at is not None else ""
    key = f"{page_id}:{stamp}:{layout_stamp}:{variant}:{nav}:{viewer}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _user_key(user: object) -> str:
    """A stable token for the signed-in principal, never its raw identifier."""
    ident = next(
        (
            value
            for attr in ("id", "sub", "email")
            if (value := getattr(user, attr, None)) not in (None, "")
        ),
        None,
    )
    raw = str(ident) if ident is not None else repr(user)
    return "u:" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def viewer_key(request: Request) -> str:
    """What about the visitor changes the rendered page: UI language + identity."""
    user = getattr(request.state, "user", None)
    ui_locale = getattr(request.state, "locale", None) or ""
    who = "anon" if user is None else _user_key(user)
    return f"{ui_locale}:{who}"


def cache_control(request: Request, settings: PagebuilderSettings) -> str:
    if getattr(request.state, "user", None) is not None:
        return SIGNED_IN_CACHE_CONTROL
    parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    return "public, " + ", ".join(parts)
