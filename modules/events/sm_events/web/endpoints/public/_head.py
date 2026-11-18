"""Server-rendered metadata for the pages events serves to the public.

The host renders one Inertia shell for every screen, with a fixed ``<title>`` and an empty head
slot, so a crawler or an unfurler that does not run JavaScript would see no description,
canonical link or structured data. The tags are written into the HTML on the way out
(:func:`inject`), and the page's ``<Head>`` repeats them for visits made inside the SPA. These
are copies of news' helpers (written here, not imported) with two differences: the JSON-LD
escape is stricter (:func:`safe_json_ld`), and event pages are ``og:type`` ``website``
(``article`` is wrong for an event).

Every value is HTML-escaped with ``quote=True``. The only script written is JSON-LD, which is not
executable and so needs no nonce under the production CSP; no executable script is added here.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from fastapi import Response

__all__ = ["event_head", "inject", "listing_head", "safe_json_ld", "set_html_lang"]

_CLOSE_HEAD = b"</head>"
_EXISTING_TITLE = re.compile(rb"<title>.*?</title>", re.S)
# ``\s`` before ``lang``, not ``\b``: ``xml:lang=`` and ``data-lang=`` are other attributes.
_HTML_LANG = re.compile(rb"""(<html\b[^>]*?\slang=)(["'])([^"']*)\2""", re.IGNORECASE)
_JSON_LD_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    chr(0x2028): "\\u2028",
    chr(0x2029): "\\u2029",
}


def _e(value: str) -> str:
    return html.escape(value, quote=True)


def _tag(name: str, value: str | None, *, prop: bool = False) -> str:
    """One meta tag, or nothing when the value is empty. ``name`` is a literal of the callers."""
    if not value:
        return ""
    key = "property" if prop else "name"
    return f'<meta {key}="{name}" content="{_e(value)}">'


def _alternate_links(alternates: list[dict[str, str]] | None) -> list[str]:
    """``hreflang`` links (``x-default`` included); none for a monolingual site."""
    return [
        f'<link rel="alternate" hreflang="{_e(entry["locale"])}" href="{_e(entry["url"])}">'
        for entry in alternates or []
    ]


def safe_json_ld(doc: Any) -> str:
    """JSON that cannot break out of its ``<script>``: ``<``, ``>``, ``&`` and the JavaScript
    line separators are written as ``\\uXXXX`` escapes, which parse back to the same document."""
    text = json.dumps(doc, ensure_ascii=True, separators=(",", ":"))
    return "".join(_JSON_LD_ESCAPES.get(char, char) for char in text)


def _common(
    *, title: str, description: str | None, canonical: str | None, locale: str | None,
    alternates: list[dict[str, str]] | None, robots: str | None,
) -> list[str]:  # fmt: skip
    parts = [
        f"<title>{_e(title)}</title>",
        _tag("description", description),
        _tag("og:title", title, prop=True),
        _tag("og:description", description, prop=True),
        _tag("og:type", "website", prop=True),
        _tag("og:url", canonical, prop=True),
        # The bare tag, not an invented ``ll_CC`` region.
        _tag("og:locale", locale, prop=True),
        _tag("robots", robots),
    ]
    parts.extend(_alternate_links(alternates))
    if canonical:
        parts.append(f'<link rel="canonical" href="{_e(canonical)}">')
    return parts


def event_head(
    *, title: str, description: str | None, canonical: str | None, image: str | None,
    index_in_search: bool, json_ld: Any, locale: str | None,
    alternates: list[dict[str, str]] | None, nonce: str | None = None,
) -> str:  # fmt: skip
    """The head an event page needs, as markup. ``nonce`` is the request's CSP nonce: the JSON-LD
    script is not executable and needs none, but carries it so every script on the page does."""
    parts = _common(
        title=title,
        description=description,
        canonical=canonical,
        locale=locale,
        alternates=alternates,
        robots=None if index_in_search else "noindex,nofollow",
    )
    parts.append(_tag("og:image", image, prop=True))
    parts.append(_tag("twitter:card", "summary_large_image" if image else "summary"))
    parts.append(_tag("twitter:image", image))
    if json_ld:
        attribute = f' nonce="{_e(nonce)}"' if nonce else ""
        parts.append(
            f'<script type="application/ld+json"{attribute}>{safe_json_ld(json_ld)}</script>'
        )
    return "".join(part for part in parts if part)


def listing_head(
    *, title: str, description: str | None, canonical: str | None, feed_url: str | None,
    locale: str | None, alternates: list[dict[str, str]] | None, robots: str | None = None,
) -> str:  # fmt: skip
    """The head the index and a calendar's page need, with feed autodiscovery."""
    parts = _common(
        title=title,
        description=description,
        canonical=canonical,
        locale=locale,
        alternates=alternates,
        robots=robots,
    )
    if feed_url:
        parts.append(
            f'<link rel="alternate" type="text/calendar" title="{_e(title)}" href="{_e(feed_url)}">'
        )
    return "".join(part for part in parts if part)


def inject(response: Response, head: str) -> Response:
    """Put ``head`` into the rendered shell before ``</head>``, replacing the shell's title.
    A response without ``</head>`` (Inertia's JSON, a 304) is returned untouched."""
    body = getattr(response, "body", None)
    if not body or _CLOSE_HEAD not in body:
        return response
    shell_head, rest = body.split(_CLOSE_HEAD, 1)
    patched = (
        _EXISTING_TITLE.sub(b"", shell_head, count=1) + head.encode("utf-8") + _CLOSE_HEAD + rest
    )
    response.body = patched
    response.headers["content-length"] = str(len(patched))
    return response


def set_html_lang(response: Response, locale: str) -> Response:
    """Rewrite the shell's ``<html lang>`` to ``locale``, keeping the shell's own value beside it
    as ``data-shell-lang`` (which the client puts back when the reader leaves a public page)."""
    body = getattr(response, "body", None)
    if not body:
        return response
    value = _e(locale).encode("utf-8")

    def rewrite(match: re.Match[bytes]) -> bytes:
        return match.group(1) + b'"' + value + b'" data-shell-lang="' + match.group(3) + b'"'

    patched = _HTML_LANG.sub(rewrite, body, count=1)
    if patched != body:
        response.body = patched
        response.headers["content-length"] = str(len(patched))
    return response
