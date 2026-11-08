"""``/newsletter/o/<token>.gif`` and ``/newsletter/c/<token>/<N>``: the open pixel
and the click redirect (T6, T10-T13).

**No CSRF, on purpose.** Both are ``GET``s a mail client makes with no session.
The signed path token is the capability, and the worst a cross-site forger
holding nothing can do is make a request that records nothing: a forged token
costs one HMAC and no query. A *genuine* token only bumps its own send's
counters, which unique counts make idempotent (T8, T9).

**The tenant comes from the token** (S8), as on the unsubscribe link: the
links are built on the host's ``public_base_url``, the apex on a multi-tenant
host, where no tenant resolves. Only a tenant the request's host resolved can
refuse a token (:mod:`~sm_newsletter.web.endpoints.public_tenant`).

**Privacy (T10).** The routes never read the client's address, its user agent
or any forwarding header, and log nothing about the request.

**One answer each.** The pixel always answers the same transparent GIF; the
click answers a 302 to the stored URL or one fixed 404, so neither is an oracle.
"""

from __future__ import annotations

import base64
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response
from simple_module_db import no_tenant

from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.web.endpoints.public_tenant import host_tenant
from sm_newsletter.web.services.tracking import click_by_token, open_by_token

__all__ = ["CLICK_PATH", "GIF", "NO_STORE", "OPEN_PATH", "router"]

_CLICK_ANY: Final = f"{constants.CLICK_PREFIX}{{rest:path}}"

OPEN_PATH: Final = f"{constants.OPEN_PREFIX}{{token}}.gif"
CLICK_PATH: Final = f"{constants.CLICK_PREFIX}{{token}}/{{position}}"

GIF: Final[bytes] = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
"""The 43-byte transparent 1x1 GIF89a."""

NO_STORE: Final[dict[str, str]] = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Expires": "0",
    # The host's security-headers middleware overwrites this with
    # ``strict-origin-when-cross-origin``, which still sends a redirect target
    # the origin only, never the token in the path (docs/tracking.md).
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
}

router = APIRouter(tags=["newsletter-public"])


@router.get(OPEN_PATH, include_in_schema=False)
async def open_pixel(request: Request, token: str) -> Response:
    resolved = host_tenant(request)
    # A visitor-derived tenant may be bound by the middleware; the service
    # binds the token's own, so leave it first.
    with no_tenant():
        await open_by_token(request.app, token, resolved_tenant=resolved, now=utcnow())
    return Response(GIF, media_type="image/gif", headers=NO_STORE)


@router.get(CLICK_PATH, include_in_schema=False)
async def click_redirect(request: Request, token: str, position: str) -> Response:
    resolved = host_tenant(request)
    with no_tenant():
        url = await click_by_token(
            request.app, token, position, resolved_tenant=resolved, now=utcnow()
        )
    if url is None:
        return _not_found()
    return RedirectResponse(url, status_code=302, headers=NO_STORE)


@router.get(_CLICK_ANY, include_in_schema=False)
async def click_malformed(rest: str) -> Response:
    """Anything else under the click prefix (no or an empty link number, extra
    segments): the click route's one fixed 404, not the host's HTML page."""
    return _not_found()


def _not_found() -> Response:
    return Response(
        constants.NOT_FOUND_DETAIL, status_code=404, media_type="text/plain", headers=NO_STORE
    )
