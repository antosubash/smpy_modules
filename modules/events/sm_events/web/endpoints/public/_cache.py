"""What a public response may be kept for, by whom, and how it is validated.

**Who may share an answer** (records #196, pagebuilder and news #192, images'
``_shared_tenant``): ``public`` only when nothing request-specific picked the tenant
(``not tenant_from_request``), the request-level mode is ``SINGLE`` and the tenant is the
host's one default. Anything else is ``private`` with the same lifetime, and names whatever
picks the tenant in ``Vary`` (the member's ``Cookie`` on a multi-tenant host, the tenant
header, whatever the framework recorded), so a shared cache keyed by URL never hands one
tenant's answer to another's reader.

**Lifetimes** all come from ``public_cache_seconds`` (``S``): a page ``max-age=S`` with
``stale-while-revalidate``; the index and calendar pages and the occurrences API
``min(S, 60)``; feeds and the sitemap ``S``. ``S = 0`` is ``no-store`` and no ``ETag``.
A page differs by visitor (the UI language, a signed-in user's name and menus), so it
varies on :data:`PER_VIEWER_VARY` and a signed-in visitor's copy is ``private, no-store``
with no validator. Every response names the origin; while the origin is guessed from
``Host`` that header joins ``Vary`` (news #355).

**Validators.** A weak ``ETag``; ``If-None-Match`` is read only *after* the row passed the
gate, by the caller, so a guessed tag on a hidden URL is a 404, never a 304. A 304 carries
``ETag``, ``Cache-Control`` and ``Vary`` and nothing else of ours (never a CSP header,
news #322).

**Errors are never stored** (records #88): :func:`error_headers` gives every public error
answer ``no-store`` and no ``ETag``, with the same tenant ``Vary`` a success has;
:class:`~sm_events.web.endpoints.public._errors.PublicErrorRoute` applies it to every error
the public routers produce. Existence is no oracle: an unknown, a hidden and a trashed target
are answered by the same code path.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Final, Literal

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from simple_module_hosting.tenancy import tenant_vary as recorded_vary

from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import (
    DEFAULT_TENANT,
    TenancyMode,
    mode_of,
    request_mode,
    resolve_public,
    tenant_from_request,
    tenant_header,
)
from sm_events.web.endpoints.public import _urls

__all__ = [
    "NO_STORE",
    "PER_VIEWER_VARY",
    "apply",
    "body_etag",
    "error_headers",
    "matches",
    "not_modified",
    "page_etag",
    "permanent_redirect",
    "shared_tenant",
    "signed_in",
    "tenant_vary",
    "viewer_key",
]

Kind = Literal["page", "listing", "feed", "sitemap", "api"]

#: What a rendered page varies on besides the URL: the representation, and the viewer.
PER_VIEWER_VARY = ("X-Inertia", "Cookie", "Accept-Language")
#: A signed-in copy embeds the user's name, roles and menus, so it is never kept and never
#: 304'd: an ETag over the user's id would vouch for stale roles.
SIGNED_IN_CACHE_CONTROL = "private, no-store"
NO_STORE: Final = "no-store"
_WEAK: Final = "W/"
_PAGE_KINDS = frozenset({"page", "listing"})


def signed_in(request: Request) -> bool:
    return getattr(request.state, "user", None) is not None


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
    return "u:" + hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:12]


def viewer_key(request: Request) -> str:
    """UI language + who is signed in, never the raw user identifier."""
    user = getattr(request.state, "user", None)
    ui_locale = getattr(request.state, "locale", None) or ""
    who = "anon" if user is None else _user_key(user)
    return f"{ui_locale}:{who}"


def shared_tenant(request: Request) -> bool:
    """Whether this request's tenant is the host-wide single-tenant fallback, which a
    shared cache may hold for every reader."""
    if tenant_from_request(request):
        return False
    single = request_mode(request, mode_of(request.app)) is TenancyMode.SINGLE
    return single and resolve_public(request) == DEFAULT_TENANT


def tenant_vary(request: Request) -> tuple[str, ...]:
    """The request headers that picked this request's tenant; none when it is shared.

    As news does (``request_vary``): whenever the tenant is not the host's one default, the answer
    varies on ``Cookie`` (a member's session may have chosen it) and the tenant header, plus what
    the framework recorded, whatever mode the stack was detected in. A request-level multi-tenant
    answer on an app detected single-tenant (a child mounted under a multi-tenant parent) is
    covered the same way."""
    if shared_tenant(request):
        return ()
    names = ["Cookie"]
    if (header := tenant_header(request.app)) is not None:
        names.append(header)
    names.extend(recorded_vary(request) or ())
    return tuple(dict.fromkeys(names))


def _drop(response: Response, name: str) -> None:
    if name in response.headers:
        del response.headers[name]


def _add_vary(response: Response, *names: str) -> None:
    listed = [f.strip() for f in response.headers.get("vary", "").split(",") if f.strip()]
    seen = {f.lower() for f in listed}
    added = [n for n in dict.fromkeys(names) if n.lower() not in seen]
    if added:
        response.headers["Vary"] = ", ".join([*listed, *added])


def page_etag(*parts: object, variant: str, viewer: str) -> str:
    """A weak validator over what a page shows: the identities and revisions in ``parts``,
    the representation (``variant``: HTML or Inertia JSON, which must never share a tag) and
    whose response it is (:func:`viewer_key`)."""
    key = "\x1f".join(
        p.isoformat() if isinstance(p, datetime) else str(p) for p in (*parts, variant, viewer)
    )
    digest = hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:16]
    return f'{_WEAK}"{digest}"'


def body_etag(body: bytes) -> str:
    """A weak validator over a response body (feeds, sitemap, the API)."""
    return f'{_WEAK}"{hashlib.sha256(body).hexdigest()[:32]}"'


def matches(if_none_match: str | None, tag: str) -> bool:
    """RFC 9110 §13.1.2: ``*`` matches anything, and the comparison is weak."""
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    wanted = tag.removeprefix(_WEAK)
    return any(
        candidate.strip().removeprefix(_WEAK) == wanted for candidate in if_none_match.split(",")
    )


def _lifetime(seconds: int, kind: Kind) -> str:
    max_age = (
        min(seconds, constants.PUBLIC_LISTING_CACHE_MAX) if kind in ("listing", "api") else seconds
    )
    policy = f"max-age={max_age}"
    if kind == "page":
        policy += f", stale-while-revalidate={constants.PUBLIC_SWR_SECONDS}"
    return policy


def apply(
    response: Response,
    request: Request,
    settings: EventsSettings,
    *,
    kind: Kind,
    etag: str | None,
    degraded: bool = False,
) -> Response:
    """Set the cache headers (and the validator, where one is allowed) on ``response``.
    ``degraded``: a plugin source did not answer, so the body is a failure's, not the
    calendar's: ``no-store`` and no validator, whatever the lifetime would be."""
    page = kind in _PAGE_KINDS
    seconds = 0 if degraded else settings.public_cache_seconds
    keep_etag = False
    if page and signed_in(request):
        response.headers["Cache-Control"] = SIGNED_IN_CACHE_CONTROL
    elif seconds <= 0:
        response.headers["Cache-Control"] = NO_STORE
    else:
        # A signed-in visitor's copy of the API is private, though it holds nothing of theirs.
        shared = shared_tenant(request) and not (kind == "api" and signed_in(request))
        scope = "public" if shared else "private"
        response.headers["Cache-Control"] = f"{scope}, {_lifetime(seconds, kind)}"
        keep_etag = etag is not None
    if keep_etag and etag is not None:
        response.headers["ETag"] = etag
    else:
        _drop(response, "ETag")
    host = ("Host",) if _urls.guessed(request.app) else ()
    _add_vary(response, *(PER_VIEWER_VARY if page else ()), *tenant_vary(request), *host)
    return response


def permanent_redirect(request: Request, settings: EventsSettings, target: str) -> Response:
    """A 301 to ``target`` (a renamed slug, the default language's redundant prefix) that is
    kept no longer than a listing and keyed like one, so a slug reclaimed later is not stuck
    in a browser's cache forever and one tenant's redirect never answers another's."""
    return apply(
        RedirectResponse(target, status_code=301), request, settings, kind="listing", etag=None
    )


def not_modified(request: Request, response_headers: Mapping[str, str]) -> Response | None:
    """A 304 for a conditional request that matches the validator in ``response_headers``,
    else ``None``. Call it only for a row that already passed the gate."""
    tag = response_headers.get("ETag")
    if tag is None or not matches(request.headers.get("if-none-match"), tag):
        return None
    kept = {
        k: response_headers[k] for k in ("ETag", "Cache-Control", "Vary") if k in response_headers
    }
    return Response(status_code=304, headers=kept)


def error_headers(request: Request, response: Response) -> Response:
    """Mark a public error answer not storable, with no validator, and per-tenant where the
    answer depends on the tenant. Anything below 400 is left alone."""
    if response.status_code < 400:
        return response
    response.headers["Cache-Control"] = NO_STORE
    _drop(response, "ETag")
    _add_vary(response, *tenant_vary(request))
    return response
