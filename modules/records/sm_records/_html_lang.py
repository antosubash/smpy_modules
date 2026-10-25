"""The ``lang`` of the document an anonymous records page is served in (#101).

The host shell hard-codes ``<html lang="en">`` and the framework's Inertia root
template takes no per-response variables, so the page's own language is
written into it on the way out. A copy of pagebuilder's ``html_lang`` (itself
a copy of news'): records must not import either module, and the rule is
small enough that sharing it would cost more than it saves. Change them
together.
"""

from __future__ import annotations

import html
import re

from fastapi import Response

__all__ = ["set_html_lang"]

# ``\s`` before ``lang``, not ``\b``: ``xml:lang=`` and ``data-lang=`` are
# other attributes, and ``\b`` would match inside either.
_HTML_LANG = re.compile(rb"""(<html\b[^>]*?\slang=)(["'])([^"']*)\2""", re.IGNORECASE)


def set_html_lang(response: Response, locale: str) -> Response:
    """Rewrite the shell's ``<html lang>`` to ``locale``, keeping the shell's
    own value as ``data-shell-lang``. Only the first match is touched."""
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
