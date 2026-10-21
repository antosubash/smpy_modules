"""The ``lang`` of the document a public page is served in (#187).

The host shell hard-codes ``<html lang="en">``, so a German page reached screen
readers, translation prompts and search engines as English. The shell belongs
to the host and is shared with every screen, and the framework's Inertia root
template takes no per-response variables, so the page's own language is
written into it on the way out. The client re-asserts it on mount
(``hooks/useDocumentLang``) for client-side visits, where no new shell is
served.

A copy of ``news.endpoints.public._lang``: the two modules do not depend on
each other, and the rule is small enough that sharing it would cost more than
it saves. Change them together.
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
    that is not a public page. Without it, a reader who arrived on a German
    page would carry ``lang="de"`` into the English console.

    Only the first match is touched — the shell's own tag precedes the page
    object embedded in the body.
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
