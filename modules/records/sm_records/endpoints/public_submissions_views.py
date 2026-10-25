"""The landing pages of a newsletter's confirm and unsubscribe links (#101, §4.2).

``GET /records/submissions/confirm?t=…&l=…`` and ``…/unsubscribe?t=…&l=…``,
at the fixed :data:`~sm_records.constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX`,
exempt from authentication for ``GET`` only. One real Inertia page,
``Records/SubmissionAction``: a button, and the result once it is pressed.

**The ``GET`` never changes anything.** Mail scanners fetch links, so a
confirmation on ``GET`` would confirm every scanned address. The page posts
the token to the API (``public_submissions_links``), and verifies nothing
itself: it answers the same for any ``t``, reads no database and binds no
tenant — there is nothing here to isolate or to leak.

It speaks ``l`` — the subscriber's language, put in the link when the mail was
built — in ``<html lang>`` and in its strings, which come from this module's
catalogue on the server (``copy``), not from the console's cookie. Every
answer is ``no-store`` and ``Referrer-Policy: no-referrer`` (a host's
security-headers middleware may replace that header; the page repeats it as a
``<meta name="referrer">``): the address carries a capability, which must not
reach a shared cache or another site's logs.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Query, Request, Response
from simple_module_hosting.inertia_deps import InertiaDep

from sm_records import constants
from sm_records._html_lang import set_html_lang
from sm_records.public_submissions import links, strings

__all__ = ["router"]

router = APIRouter()

_COPY_KEYS: Final = {
    links.CONFIRM: ("title", "intro", "button", "done", "already", "expired"),
    links.UNSUBSCRIBE: ("title", "intro", "button", "done"),
}
_COMMON_KEYS: Final = ("sending", "failed")


def _copy(action: str, locale: str) -> dict[str, str]:
    words = {key: strings.text(f"landing.{action}.{key}", locale) for key in _COPY_KEYS[action]}
    words.update({key: strings.text(f"landing.{key}", locale) for key in _COMMON_KEYS})
    return words


async def _page(request: Request, inertia: InertiaDep, action: str, t: str, lang: str) -> Response:
    locale = strings.catalogue_locale(lang)
    token = t if len(t) <= links.MAX_LINK_TOKEN else ""
    response = await inertia.render(
        constants._PAGE_SUBMISSION_ACTION,
        {
            "action": action,
            "token": token,
            "locale": locale,
            "endpoint": f"{constants.PUBLIC_SUBMISSIONS_API_PREFIX}{action}",
            "copy": _copy(action, locale),
        },
    )
    if not request.headers.get("x-inertia"):
        set_html_lang(response, locale)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Language"] = locale
    return response


@router.get("/confirm", response_model=None)
async def confirm_page(
    request: Request,
    inertia: InertiaDep,
    t: str = Query(default=""),
    lang: str = Query(default="", alias="l"),
) -> Response:
    """The *Confirm subscription* button. Changes nothing until pressed."""
    return await _page(request, inertia, links.CONFIRM, t, lang)


@router.get("/unsubscribe", response_model=None)
async def unsubscribe_page(
    request: Request,
    inertia: InertiaDep,
    t: str = Query(default=""),
    lang: str = Query(default="", alias="l"),
) -> Response:
    """The *Unsubscribe* button. Changes nothing until pressed."""
    return await _page(request, inertia, links.UNSUBSCRIBE, t, lang)
