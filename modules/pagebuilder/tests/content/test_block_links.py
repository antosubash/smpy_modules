"""Block links are checked when a page or the layout is saved (#354).

Every prop named ``href`` or ending in ``Href``, at any depth, and every
Markdown link target in a string prop must be scheme-less (relative) or
http(s), mailto or tel. Anything else — ``javascript:``, ``data:``,
``vbscript:`` — is a 422 naming the block and the field.
"""

from __future__ import annotations

import pytest
from pagebuilder.content.links import UnsafeLinkError, check_links, is_safe_href

pytestmark = pytest.mark.asyncio

PAGES = "/api/pagebuilder/pages"
LAYOUT = "/api/pagebuilder/layout"


def _doc(*blocks: dict) -> dict:
    return {"root": {"props": {"title": "T"}}, "content": list(blocks), "zones": {}}


def _button(href: str, block_id: str = "Button-1") -> dict:
    return {"type": "Button", "props": {"id": block_id, "label": "Go", "href": href}}


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
async def test_allowed_links(href):
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
async def test_refused_links(href):
    assert not is_safe_href(href)


async def test_the_message_names_the_block_and_a_nested_field():
    doc = _doc(
        {
            "type": "SiteHeader",
            "props": {
                "id": "SiteHeader-7",
                "links": [{"label": "ok", "href": "/"}, {"label": "x", "href": "javascript:x"}],
            },
        }
    )
    expected = r"SiteHeader \(SiteHeader-7\), field links\[1\]\.href"
    with pytest.raises(UnsafeLinkError, match=expected):
        check_links(doc)


async def test_a_prop_ending_in_href_is_checked():
    doc = _doc({"type": "Hero", "props": {"id": "h", "primaryHref": "data:text/html,x"}})
    with pytest.raises(UnsafeLinkError, match="field primaryHref"):
        check_links(doc)


async def test_a_markdown_link_in_text_is_checked_but_an_image_source_is_not():
    bad = _doc({"type": "Text", "props": {"id": "t", "text": "see [this](javascript:x)"}})
    with pytest.raises(UnsafeLinkError, match=r"Text \(t\), field text"):
        check_links(bad)
    # Not a link: image sources are out of scope, and a linked image's target is
    # what is checked.
    check_links(_doc({"type": "Text", "props": {"id": "t", "text": "![a](data:image/png,x)"}}))
    linked = _doc({"type": "Text", "props": {"id": "t", "text": "[![a](/a.png)](vbscript:x)"}})
    with pytest.raises(UnsafeLinkError):
        check_links(linked)


async def test_blocks_in_zones_and_slots_are_found():
    nested = {
        "type": "Columns",
        "props": {"id": "c", "left": [_button("javascript:x", "Button-inner")]},
    }
    with pytest.raises(UnsafeLinkError, match=r"Button \(Button-inner\)"):
        check_links(_doc(nested))
    zoned = {"root": {}, "content": [], "zones": {"c:left": [_button("javascript:x", "B-z")]}}
    with pytest.raises(UnsafeLinkError, match=r"Button \(B-z\)"):
        check_links(zoned)


async def test_a_page_save_refuses_an_unsafe_link(authed_client):
    created = await authed_client.post(
        PAGES,
        json={"title": "x", "slug": "x", "draft_data": _doc(_button("javascript:alert(1)"))},
    )
    assert created.status_code == 422
    assert "Button (Button-1), field href" in created.text

    ok = await authed_client.post(
        PAGES, json={"title": "x", "slug": "x", "draft_data": _doc(_button("/about"))}
    )
    assert ok.status_code == 201, ok.text

    updated = await authed_client.put(
        f"{PAGES}/{ok.json()['id']}", json={"draft_data": _doc(_button("vbscript:x"))}
    )
    assert updated.status_code == 422
    assert "Button (Button-1), field href" in updated.text
    stored = await authed_client.get(f"{PAGES}/{ok.json()['id']}")
    assert stored.json()["draft_data"]["content"][0]["props"]["href"] == "/about"


async def test_a_layout_save_refuses_an_unsafe_link(authed_client):
    footer = _doc(
        {
            "type": "SiteFooter",
            "props": {"id": "F-1", "columns": [{"links": [{"href": "data:text/html,x"}]}]},
        }
    )
    response = await authed_client.put(LAYOUT, json={"footer_data": footer})
    assert response.status_code == 422
    assert "SiteFooter (F-1), field columns[0].links[0].href" in response.text

    fine = await authed_client.put(LAYOUT, json={"footer_data": _doc(_button("mailto:a@b.org"))})
    assert fine.status_code == 200, fine.text
