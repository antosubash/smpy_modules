"""Server-rendered metadata for the pages news serves to the public.

The host renders one Inertia shell for every screen: a fixed
``<title>SimpleModule</title>`` and a ``{% inertia_head %}`` slot that only
fills when server-side rendering is configured. Nothing here configures it, so
the slot comes back empty and every public page ships the same head.

For the admin console that is fine — nothing crawls it. For an archive it is
not. `PublicArticle` composes a careful set of ``og:*`` tags, a description, a
canonical link and JSON-LD through Inertia's ``<Head>``, and every one of them
exists only after JavaScript runs. Google executes JavaScript; Slack, X,
LinkedIn, Facebook and most feed tooling do not. So a link to an article
previewed as "SimpleModule" with no description and no image.

This is the smallest fix that works from inside a module: render the tags into
the HTML on the way out. It does not make the *body* server-rendered — that
would mean reimplementing twenty-one React blocks in Python — but the body was
never what an unfurler wanted.

The proper fix is server-side rendering in the host, at which point the
``<Head>`` tags arrive through ``{% inertia_head %}`` and this becomes dead
weight. Until then the choice is between duplicate tags under SSR (harmless,
and detectable — see ``inject``) and no tags at all without it.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from fastapi import Response

_CLOSE_HEAD = b"</head>"


def _tag(name: str, value: str | None, *, prop: bool = False) -> str:
    """One meta tag, or nothing when the value is empty.

    The value is HTML-escaped with ``quote=True``: these are author-written
    strings landing in an attribute, and a headline containing a quotation mark
    is ordinary rather than an attack. ``name`` is a literal from the call sites
    below, never user input.
    """
    if not value:
        return ""
    key = "property" if prop else "name"
    return f'<meta {key}="{name}" content="{html.escape(value, quote=True)}">'


def article_head(
    *,
    title: str,
    description: str | None,
    canonical: str | None,
    image: str | None,
    site_name: str | None,
    twitter_handle: str | None,
    published_at: str | None,
    author: str | None,
    section: str | None,
    index_in_search: bool,
    json_ld: dict[str, Any] | None,
) -> str:
    """The head an article needs, as markup.

    Mirrors what ``PublicArticle.tsx`` renders client-side. The duplication is
    the point rather than an oversight: one copy serves the crawler that never
    runs the script, the other serves the reader who navigated in through the
    SPA and never reloaded, and neither can cover the other's case.
    """
    parts = [
        f"<title>{html.escape(title)}</title>",
        _tag("description", description),
        _tag("og:title", title, prop=True),
        _tag("og:description", description, prop=True),
        # ``article``, not ``website``: the whole reason this module took its
        # own address is that these documents are not generic pages.
        _tag("og:type", "article", prop=True),
        _tag("og:url", canonical, prop=True),
        _tag("og:site_name", site_name, prop=True),
        _tag("og:image", image, prop=True),
        _tag("article:published_time", published_at, prop=True),
        _tag("article:author", author, prop=True),
        _tag("article:section", section, prop=True),
        _tag("twitter:card", "summary_large_image" if image else "summary"),
        _tag("twitter:image", image),
        _tag("twitter:site", twitter_handle),
    ]
    if canonical:
        parts.append(f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">')
    if not index_in_search:
        parts.append('<meta name="robots" content="noindex,nofollow">')
    if json_ld:
        parts.append(
            '<script type="application/ld+json">'
            f"{_safe_json_ld(json_ld)}</script>"
        )
    return "".join(part for part in parts if part)


def listing_head(
    *,
    title: str,
    description: str | None,
    canonical: str | None,
    site_name: str | None,
    feed_url: str | None,
) -> str:
    """The head an archive page needs.

    ``og:type`` is ``website`` here and ``article`` above, which is the
    distinction the split was about in the first place.
    """
    parts = [
        f"<title>{html.escape(title)}</title>",
        _tag("description", description),
        _tag("og:title", title, prop=True),
        _tag("og:description", description, prop=True),
        _tag("og:type", "website", prop=True),
        _tag("og:url", canonical, prop=True),
        _tag("og:site_name", site_name, prop=True),
    ]
    if canonical:
        parts.append(f'<link rel="canonical" href="{html.escape(canonical, quote=True)}">')
    if feed_url:
        # Feed autodiscovery: this is the tag a reader's browser extension and
        # every feed reader looks for, and without it the feed exists but is
        # findable only by guessing its address.
        parts.append(
            '<link rel="alternate" type="application/rss+xml" '
            f'title="{html.escape(title, quote=True)}" '
            f'href="{html.escape(feed_url, quote=True)}">'
        )
    return "".join(part for part in parts if part)


def _safe_json_ld(doc: dict[str, Any]) -> str:
    """Serialize JSON-LD so it cannot break out of its ``<script>``.

    ``json.dumps`` does not escape the literal ``</`` sequence, so a value
    containing ``</script>`` would close the element early. ``<\\/`` parses
    identically to ``</`` inside JSON, so the document round-trips.
    """
    return (
        json.dumps(doc)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
    )


_EXISTING_TITLE = re.compile(rb"<title>.*?</title>", re.S)


def inject(response: Response, head: str) -> Response:
    """Put ``head`` into the rendered shell, immediately before ``</head>``.

    The shell's own ``<title>`` is removed first, whatever it says — the host
    hard-codes its application name there, and a document carrying two titles
    lets the consumer pick, which in practice means the wrong one.

    Returns the response untouched when there is nothing to inject into: an
    Inertia XHR answers JSON rather than a document, and a 304 has no body at
    all. Both are matched by the absence of ``</head>`` rather than by sniffing
    the request, so this cannot disagree with what was actually rendered.

    If the host ever enables SSR, ``{% inertia_head %}`` starts emitting the
    same tags from `PublicArticle`'s ``<Head>` and the document would carry each
    twice. Harmless — every consumer takes the first — but that is the moment to
    delete this module, not to make it cleverer.
    """
    body = getattr(response, "body", None)
    if not body or _CLOSE_HEAD not in body:
        return response
    shell_head, rest = body.split(_CLOSE_HEAD, 1)
    patched = (
        _EXISTING_TITLE.sub(b"", shell_head, count=1)
        + head.encode("utf-8")
        + _CLOSE_HEAD
        + rest
    )
    response.body = patched
    response.headers["content-length"] = str(len(patched))
    return response
