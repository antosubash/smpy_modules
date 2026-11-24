"""Article body links and embed sources are validated on save (#364).

Mirrors pagebuilder's block-link check (#354): ``Embed.url``, ``Video.url`` and
``Audio.url`` allow only http(s) or relative addresses; ``Sources.items`` lines,
``href``/``*Href`` props and Markdown links also allow ``mailto:`` and ``tel:``.
"""

from __future__ import annotations

import pytest
from news.content.links import UnsafeLinkError, check_links, is_safe_href

pytestmark = pytest.mark.asyncio

ARTICLES = "/api/news/articles"


def _doc(*blocks: dict) -> dict:
    return {"root": {"props": {"title": "T"}}, "content": list(blocks), "zones": {}}


async def _make_article(client, slug: str = "story") -> int:
    created = await client.post(ARTICLES, json={"title": "Story", "slug": slug})
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest.mark.parametrize(
    "href",
    [
        "/about",
        "#top",
        "?q=1",
        "./x",
        "contact",
        "//cdn.example/x",
        "https://example.org",
        "HTTP://example.org",
        "mailto:a@example.org",
        "tel:+43123",
        "",
    ],
)
async def test_allowed_links(href: str) -> None:
    assert is_safe_href(href)


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)",
        "\x01javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>x</script>",
        "vbscript:msgbox",
        "ftp://example.org",
        "asset://hero.png",
    ],
)
async def test_refused_links(href: str) -> None:
    assert not is_safe_href(href)


@pytest.mark.parametrize("block", ["Embed", "Video", "Audio"])
@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "mailto:a@b.org",
        "tel:+123",
        "\x01https://example.org/x",
    ],
)
async def test_media_and_embed_urls_are_http_or_relative_only(block: str, url: str) -> None:
    doc = _doc({"type": block, "props": {"id": "m-1", "url": url}})
    with pytest.raises(UnsafeLinkError, match=rf"{block} \(m-1\), field url.*http\(s\) address"):
        check_links(doc)


@pytest.mark.parametrize("block", ["Embed", "Video", "Audio"])
@pytest.mark.parametrize("url", ["https://player.example/v/1", "http://cdn.example/a.mp4", "/a.mp4", ""])
async def test_http_or_relative_media_and_embed_urls_pass(block: str, url: str) -> None:
    check_links(_doc({"type": block, "props": {"id": "m-1", "url": url}}))


@pytest.mark.parametrize(
    ("items", "expected_field"),
    [
        ("Report | javascript:alert(1)", r"items\[0\]"),
        ("\nCitation without url\n\nBad | data:text/html,x", r"items\[1\]"),
        ("Title | vbscript:msgbox(1)", r"items\[0\]"),
        ("Title | \x01javascript:x", r"items\[0\]"),
        (" | javascript:x", r"items\[0\]"),
    ],
)
async def test_sources_items_refuses_unsafe_href(items: str, expected_field: str) -> None:
    doc = _doc({"type": "Sources", "props": {"id": "s-1", "items": items}})
    with pytest.raises(UnsafeLinkError, match=rf"Sources \(s-1\), field {expected_field}"):
        check_links(doc)


async def test_sources_items_allows_safe_schemes_and_citations() -> None:
    items = (
        "Interview, March 2024\n"
        "Report | https://example.org/a\n"
        "Desk | mailto:desk@example.org\n"
        "Line | tel:+43123\n"
        "Archive | /docs/brief.pdf\n"
    )
    check_links(_doc({"type": "Sources", "props": {"id": "s-1", "items": items}}))


async def test_markdown_and_block_shaped_bypass_are_checked() -> None:
    bad_md = _doc({"type": "Paragraph", "props": {"id": "p-1", "text": "see [x](javascript:1)"}})
    with pytest.raises(UnsafeLinkError, match=r"Paragraph \(p-1\), field text"):
        check_links(bad_md)
    bypass = {
        **_doc({"type": "Sources", "props": {"id": "s-1", "items": "X | javascript:x"}}),
        "type": "ignored",
        "props": {},
    }
    with pytest.raises(UnsafeLinkError, match=r"Sources \(s-1\), field items\[0\]"):
        check_links(bypass)


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (
            {"type": "Embed", "props": {"id": "e-1", "url": "javascript:alert(1)"}},
            "Embed (e-1), field url",
        ),
        (
            {"type": "Video", "props": {"id": "v-1", "url": "data:text/html,x"}},
            "Video (v-1), field url",
        ),
        (
            {"type": "Audio", "props": {"id": "a-1", "url": "mailto:x@example.org"}},
            "Audio (a-1), field url",
        ),
        (
            {"type": "Sources", "props": {"id": "s-1", "items": "Ref | javascript:alert(1)"}},
            "Sources (s-1), field items[0]",
        ),
    ],
)
async def test_body_save_refuses_unsafe_links_with_422(
    editor_client, block: dict, expected: str
) -> None:
    article_id = await _make_article(editor_client, f"unsafe-{block['type'].lower()}")
    response = await editor_client.put(
        f"{ARTICLES}/{article_id}/body",
        json={"draft_data": _doc(block)},
    )
    assert response.status_code == 422
    assert expected in response.text


async def test_body_save_accepts_safe_links(editor_client) -> None:
    article_id = await _make_article(editor_client, "safe-body")
    doc = _doc(
        {"type": "Embed", "props": {"id": "e-1", "url": "https://example.org/embed"}},
        {"type": "Video", "props": {"id": "v-1", "url": "/media/clip.mp4"}},
        {"type": "Audio", "props": {"id": "a-1", "url": "https://cdn.example/clip.mp3"}},
        {"type": "Sources", "props": {"id": "s-1", "items": "Report | https://example.org/r"}},
    )
    response = await editor_client.put(
        f"{ARTICLES}/{article_id}/body",
        json={"draft_data": doc},
    )
    assert response.status_code == 200, response.text
