"""``/newsletter/u/<token>``: the unsubscribe page and RFC 8058's one-click POST (S8, S9).

``GET`` renders a page with one button and does nothing else: no statement, no
tenant binding, so a mail scanner that follows links unsubscribes nobody.
``POST`` - the button's empty form, or a mailbox provider's
``List-Unsubscribe=One-Click`` - does the opt-out
(:func:`~sm_newsletter.web.services.unsubscribe.unsubscribe_by_token`). Any
body is accepted and none is read.

**No CSRF, on purpose.** The one-click POST comes from the mailbox provider
with no session or cookie, and the button posts from a mail client's browser.
The signed path token is the capability, and a cross-site forger cannot mint
one: the MAC covers the tenant, campaign and send.

**The tenant comes from the token**, as records' newsletter links do
(``sm_records/web/endpoints/api/public_submissions_links.py``). The links are
built on the host's ``public_base_url``, which on a multi-tenant host is the
apex, where no tenant resolves, so binding the request's tenant would refuse
every link. The MAC is verified before any statement, and a request whose host
did resolve a tenant must name the token's, or the token counts as forged.

**One answer.** A real, ``test``, forged, oversized, already-used or
other-tenant token gets the same 200 page, so the route is no oracle and a
second click sees what the first did. The language is the host's
``i18n_default_locale``, the same as the email's footer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from sm_newsletter.core import constants, tenancy
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.messages import server_copy
from sm_newsletter.web.endpoints.unsubscribe_page import KEYS, render_page
from sm_newsletter.web.services.unsubscribe import unsubscribe_by_token

__all__ = ["PATH", "router"]

PATH = f"{constants.UNSUBSCRIBE_PREFIX}{{token}}"

router = APIRouter(tags=["newsletter-public"])


def _page(request: Request, *, done: bool) -> HTMLResponse:
    locale, copy = server_copy(request.app, "unsubscribe_page", KEYS)
    return HTMLResponse(
        render_page(copy=copy, locale=locale, done=done),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
            "Content-Language": locale,
        },
    )


@router.get(PATH, response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe_page(request: Request, token: str) -> HTMLResponse:
    return _page(request, done=False)


@router.post(PATH, response_class=HTMLResponse, include_in_schema=False)
async def unsubscribe_one_click(request: Request, token: str) -> HTMLResponse:
    await unsubscribe_by_token(
        request.app,
        token,
        resolved_tenant=tenancy._resolved(request),
        now=utcnow(),
    )
    return _page(request, done=True)
