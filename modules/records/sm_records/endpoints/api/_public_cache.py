"""Making an anonymous read cacheable: a validator and a policy.

``GET {public_route_prefix}/…`` is the one surface in this module with no
session behind it, which makes it the one a CDN, a reverse proxy or a browser
can hold — and it sent neither ``ETag`` nor ``Cache-Control``, so every
anonymous reader paid for a full page build and a full body.

Two headers, one setting (:attr:`~sm_records.settings.RecordsSettings.public_cache_seconds`):

* a **weak** ``ETag`` over the payload that is about to be serialised. Weak
  because the bytes FastAPI finally writes are the encoder's rather than
  pydantic's, and a strong validator is a promise about octets. What the
  digest covers is the response's *content*, so it changes when — and only
  when — the answer does: a row edited, a row unpublished out of the page, a
  different ``?filter=``, a different page of the same query.
* ``Cache-Control: public, max-age=<seconds>``, or ``no-store`` at ``0``, for
  an install whose "published" means "visible the instant it is saved".

**A conditional GET that matches is a 304 with no body**, which is the half
that saves bandwidth; the digest itself still costs a page build, and cannot
not, because the answer is what is being hashed.

**On a multi-tenant host the answer depends on the tenant** (tenancy design
§H), which the framework resolves from the caller's header — so every public
response there names that header in ``Vary``, on the 304 too. Without it a
cache keyed by URL would hand ``acme``'s list to a ``globex`` reader. The
header's name is the one the host gave its ``TenantMiddleware``, captured by
:func:`sm_records.tenancy.configure`. A signed-in caller's tenant comes from
their account instead, which no request header names, so their response is
``private``: a browser may keep it, a shared cache may not. The ETag stays a
content digest: two tenants whose pages are equal share it, harmlessly.

Nothing here is used on the admin API: those responses are per-caller and the
framework's ``InertiaCache`` already forces them private.

**Note for the upstream issue, not a thing to work around here.** Every
anonymous response from a host running the framework also carries
``Vary: Cookie`` and a fresh ``Set-Cookie: session=…`` — observed on the live
dev host, where the cookie decodes to ``{"__i18n_locale": "en"}``. It is
written by ``simple_module_hosting/_inertia_shared.py:54``
(``session_dict[_I18N_SESSION_LOCALE_KEY] = locale``), reached from
``InertiaLayoutDataMiddleware.__call__`` (``middleware.py:259``), which runs
for *every* HTTP request including this one: for a caller with no cookie the
stored locale never matches, so the session is marked modified on every
request and Starlette's ``SessionMiddleware`` emits a new cookie. A response
carrying ``Set-Cookie`` is not storable by a shared cache, so until that is
fixed upstream these headers help a browser and a private cache and not a CDN.
This module does not touch ``request.session`` anywhere, and works around
none of it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request, Response

from sm_records import constants
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode, mode_of, tenant_header

__all__ = ["NO_STORE", "apply"]

NO_STORE = "no-store"
"""What ``public_cache_seconds = 0`` sends instead of a ``max-age``. Not
``max-age=0``: that is still a cacheable response with a stale entry, and an
operator who set zero meant "do not keep this"."""

_WEAK = "W/"
_DIGEST_CHARS = 32


def _etag(payload: Any) -> str:
    """A weak validator over the payload's own JSON.

    ``model_dump_json`` and not the rendered response, because the handler has
    the model and not the bytes — and because the model is the stable thing:
    field order comes from the class, so the same content always digests the
    same way, while an encoder detail could change the digest without the
    content changing.
    """
    body = payload.model_dump_json() if hasattr(payload, "model_dump_json") else str(payload)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    return f'{_WEAK}"{digest}"'


def _matches(header: str | None, tag: str) -> bool:
    """RFC 9110 §13.1.2: ``*`` matches anything, and the comparison is weak.

    Weak comparison is the only one defined for ``If-None-Match``, and it is
    what lets a weak validator be useful at all: ``W/"abc"`` and ``"abc"``
    are the same entity for this purpose, so a proxy that stripped the prefix
    still gets its 304.
    """
    if not header:
        return False
    if header.strip() == "*":
        return True
    wanted = tag.removeprefix(_WEAK)
    return any(candidate.strip().removeprefix(_WEAK) == wanted for candidate in header.split(","))


def _tenancy(request: Request) -> tuple[str | None, bool]:
    """``(header to name in Vary, whether the answer is private)``.

    Single mode: ``(None, False)`` — every read is ``default``, whoever asks.
    """
    if mode_of(request.app) is TenancyMode.SINGLE:
        return None, False
    services = getattr(request.app.state, constants.PACKAGE, None)
    header = getattr(services, "tenant_header", None) or tenant_header(request.app)
    return header, getattr(request.state, "user", None) is not None


def _add_vary(headers: Any, name: str) -> None:
    existing = [v.strip() for v in headers.get("Vary", "").split(",") if v.strip()]
    if name.lower() not in {v.lower() for v in existing}:
        headers["Vary"] = ", ".join([*existing, name])


def apply(
    request: Request, response: Response, payload: Any, settings: RecordsSettings
) -> Response | None:
    """Set the cache headers for this read; return a 304 to send instead.

    ``response`` is the one FastAPI injects, so headers set on it survive the
    handler returning a model. The 304 is returned rather than raised because
    it is a response and not an error — nothing went wrong, and there is
    nothing for ``RecordsErrorRoute`` to roll back.
    """
    vary, private = _tenancy(request)
    if vary is not None:
        _add_vary(response.headers, vary)
    seconds = settings.public_cache_seconds
    if seconds <= 0:
        response.headers["Cache-Control"] = NO_STORE
        return None
    policy = f"{'private' if private else 'public'}, max-age={seconds}"
    tag = _etag(payload)
    response.headers["ETag"] = tag
    response.headers["Cache-Control"] = policy
    if _matches(request.headers.get("if-none-match"), tag):
        # The validator, the policy and ``Vary`` travel with the 304 too: a
        # cache that is refreshing an entry has to learn the new freshness
        # lifetime from somewhere, and this is the only response it is getting.
        not_modified = Response(status_code=304, headers={"ETag": tag, "Cache-Control": policy})
        if vary is not None:
            _add_vary(not_modified.headers, vary)
        return not_modified
    return None
