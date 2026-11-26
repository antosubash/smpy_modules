"""The ``lang`` of the document a public news page is served in.

The host shell hard-codes ``<html lang="en">``, so a German article reached
screen readers, translation prompts and search engines as English. The shell is
the host's and shared with every screen, so the page's own language is written
into it on the way out, beside the head tags ``_head.inject`` adds. The client
re-asserts it on mount (``useDocumentLang``) for client-side navigations, where
no new shell is served.
"""

from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

# ``\s`` before ``lang``, not ``\b``: ``xml:lang=`` and ``data-lang=`` are
# other attributes, and ``\b`` would match inside either.
_HTML_LANG = re.compile(rb"""(<html\b[^>]*?\slang=)(["'])([^"']*)\2""", re.IGNORECASE)


def set_html_lang(response: Response, locale: str) -> Response:
    """Rewrite the shell's ``<html lang>`` to ``locale``; untouched without one.

    The shell's own value is kept beside it as ``data-shell-lang``, which is
    what ``useDocumentLang`` puts back when the reader moves on to a screen
    that is not a public news page. Without it, a reader who arrived on a
    German article would carry ``lang="de"`` into the English console.
    """
    body = getattr(response, "body", None)
    if not body:
        return response
    value = html.escape(locale, quote=True).encode("utf-8")

    def rewrite(match: re.Match[bytes]) -> bytes:
        shell = match.group(3)
        return match.group(1) + b'"' + value + b'" data-shell-lang="' + shell + b'"'

    patched = _HTML_LANG.sub(rewrite, body, count=1)
    if patched != body:
        response.body = patched
        response.headers["content-length"] = str(len(patched))
    return response


def use_content_locale(locale: str) -> Callable[[Request], Awaitable[None]]:
    """A route dependency that serves the page's strings in ``locale`` (#450).

    The framework ships one catalogue with a page, chosen for the *reader* (the
    ``locale`` cookie, then ``Accept-Language``). ``/de/news/`` is a German
    address, so a visitor whose browser says English got a German page with the
    module's own words in English, beside pagebuilder's German chrome, which
    reads its strings for the content locale instead. The page is the same for
    every visitor to an address, which is also what lets a shared cache hold it.

    Setting ``request.state.locale`` is enough, because the shared props are
    built lazily at render time from it. It must run before the endpoint's own
    ``InertiaDep`` resolves them, which a router-level dependency does.

    A content locale the console has no catalogue for (a site publishing in
    ``fr`` while the host ships ``en`` and ``de``) keeps the reader's language
    rather than a catalogue of raw keys; ``de-at`` falls back to ``de``.
    """

    async def dependency(request: Request) -> None:
        registry = getattr(getattr(request.app.state, "sm", None), "i18n_registry", None)
        if registry is None:
            return
        available = {tag.lower(): tag for tag in registry.available_locales()}
        wanted = locale.lower()
        for tag in (wanted, wanted.split("-", 1)[0]):
            if tag in available:
                request.state.locale = available[tag]
                return

    return dependency
