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

from fastapi import Response

_HTML_LANG = re.compile(rb"""(<html\b[^>]*?\blang=)(["'])([^"']*)\2""", re.IGNORECASE)


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
