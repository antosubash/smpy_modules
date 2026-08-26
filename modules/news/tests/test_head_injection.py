"""The head transformation itself, without a request in the way.

Its own module rather than a class inside ``test_server_rendered_head``: these
are synchronous, and that file carries a module-level ``asyncio`` mark which
would warn on every one of them.
"""

from __future__ import annotations

from fastapi import Response
from news.endpoints.public import _head


def test_it_leaves_a_body_with_no_head_alone() -> None:
    # An Inertia XHR answers JSON, and a 304 has no body at all. Both are
    # matched by the absence of `</head>` rather than by sniffing the request,
    # so this cannot disagree with what was actually rendered.
    response = Response(content=b'{"component":"News/PublicArticle"}')

    assert _head.inject(response, "<title>x</title>").body == (
        b'{"component":"News/PublicArticle"}'
    )


def test_it_replaces_whatever_title_the_shell_carried() -> None:
    response = Response(content=b"<html><head><title>Anything</title></head></html>")

    patched = _head.inject(response, "<title>Ours</title>").body.decode()

    assert patched.count("<title>") == 1
    assert "<title>Ours</title>" in patched
    assert "Anything" not in patched


def test_it_injects_when_the_shell_has_no_title_at_all() -> None:
    response = Response(content=b"<html><head></head><body></body></html>")

    patched = _head.inject(response, "<title>Ours</title>").body.decode()

    assert "<title>Ours</title></head>" in patched


def test_it_corrects_content_length() -> None:
    # Otherwise the client is told to expect the shell's length and the
    # document truncates mid-head.
    response = Response(content=b"<html><head></head><body></body></html>")

    patched = _head.inject(response, "<title>Ours</title>")

    assert int(patched.headers["content-length"]) == len(patched.body)


def test_it_leaves_the_body_untouched() -> None:
    # Only the head is rewritten. The document itself is Inertia's.
    response = Response(
        content=b'<html><head></head><body><div id="app" data-page="x"></div></body></html>'
    )

    patched = _head.inject(response, "<title>Ours</title>").body.decode()

    assert '<div id="app" data-page="x"></div>' in patched


def test_an_empty_value_emits_no_tag() -> None:
    head = _head.article_head(
        title="T",
        description=None,
        canonical=None,
        image=None,
        site_name=None,
        twitter_handle=None,
        published_at=None,
        author=None,
        section=None,
        index_in_search=True,
        json_ld=None,
    )

    assert "og:image" not in head
    assert "og:site_name" not in head
    assert 'content=""' not in head


def test_a_listing_head_without_a_feed_omits_autodiscovery() -> None:
    head = _head.listing_head(
        title="T", description=None, canonical=None, site_name=None, feed_url=None
    )

    assert "alternate" not in head
