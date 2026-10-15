"""``POST /i18n/set-locale`` — what the framework's language switcher submits.

The ``ui`` package's LocaleSwitcher (and the users module's preferences card)
post a ``locale`` form field here, but framework 0.0.35 registers no such
route, so choosing a language landed on a 404 and changed nothing. This host
is the first in this repo to offer a second console language, which is what
surfaced it; the route belongs upstream, and this goes once the framework
ships one.

It writes the cookie ``LocaleMiddleware`` reads (``i18n_cookie_name``) and
sends the browser back where it came from. Only a supported locale is
accepted, and only a same-origin path is followed back, so the form cannot
be used to set junk cookies or as an open redirect.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from simple_module_hosting import Settings

ONE_YEAR = 365 * 24 * 60 * 60


def locale_switch_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.post("/i18n/set-locale", include_in_schema=False)
    async def set_locale(request: Request, locale: str = Form("")) -> RedirectResponse:
        response = RedirectResponse(_back(request), status_code=303)
        if locale in settings.i18n_supported_locales:
            response.set_cookie(
                settings.i18n_cookie_name,
                locale,
                max_age=ONE_YEAR,
                path="/",
                samesite="lax",
                secure=request.url.scheme == "https",
            )
        return response

    return router


def _back(request: Request) -> str:
    """The page the switch was made from, as a path — never another site."""
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.netloc and referer.netloc != request.url.netloc:
        return "/"
    path = referer.path or "/"
    # Browsers read a backslash as a slash, so "/\\host" is "//host" to them.
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return f"{path}?{referer.query}" if referer.query else path
