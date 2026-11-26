"""Shared head escaping and injection; the page renderers are in ``_head_pages``.

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


# The attribute Inertia's head manager keys on. An element in ``document.head``
# carrying it is *managed*: on hydration the client's ``<Head>`` replaces the
# managed element with the same key instead of appending a second copy, and
# removes one the page no longer renders. An element without it is invisible to
# the manager, so a client tag beside it is simply added: two canonicals, two of
# every ``og:`` tag. The React side sets the same key through ``head-key``
# (``ArticleHead``, ``ArchiveHead``), rendering the same resolved ``head`` prop.
# Titles are replaced specially by Inertia; every other tag is managed.
_MANAGED = "data-inertia"
KEY_CANONICAL = "canonical"
KEY_ROBOTS = "robots"
KEY_JSON_LD = "json-ld"


def _tag(
    name: str, value: str | None, *, prop: bool = False, managed: bool = False
) -> str:
    """One meta tag, or nothing when the value is empty.

    ``managed`` marks a tag the client's ``<Head>`` renders under the same key
    (the tag's own name), so hydration adopts it rather than duplicating it.

    The value is HTML-escaped with ``quote=True``: these are author-written
    strings landing in an attribute, and a headline containing a quotation mark
    is ordinary rather than an attack. ``name`` is a literal from the call sites
    below, never user input.
    """
    if not value:
        return ""
    key = "property" if prop else "name"
    keyed = f' {_MANAGED}="{name}"' if managed else ""
    return f'<meta {key}="{name}"{keyed} content="{html.escape(value, quote=True)}">'


def _alternate_links(
    alternates: list[dict[str, str]] | None, *, managed: bool = False
) -> list[str]:
    """``hreflang`` links for a document that exists in several languages.

    Server-rendered rather than left to Inertia's ``<Head>`` for the same reason
    everything else here is: a crawler deciding which language to index for a
    query does it without running the script, and a switch it never sees is a
    switch that does not exist.

    Empty for a monolingual site — see ``alternates`` in ``_article``, which
    returns nothing rather than a lone entry pointing at the document itself.

    ``managed`` keys each link ``hreflang-<locale>``, for a client that renders
    the same set through ``<Head>`` (news and events both do this).
    """
    return [
        '<link rel="alternate" '
        + (f'{_MANAGED}="hreflang-{html.escape(entry["locale"], quote=True)}" ' if managed else "")
        + f'hreflang="{html.escape(entry["locale"], quote=True)}" '
        f'href="{html.escape(entry["url"], quote=True)}">'
        for entry in alternates or []
    ]


def _safe_json_ld(doc: dict[str, Any]) -> str:
    """Serialize JSON-LD so it cannot break out of its ``<script>``.

    ``json.dumps`` does not escape the literal ``</`` sequence, so a value
    containing ``</script>`` would close the element early. ``<\\/`` parses
    identically to ``</`` inside JSON, so the document round-trips.
    """
    return (
        json.dumps(doc)
        .replace("</", "<\\/")
        .replace("<!--", "<\\u0021--")
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
