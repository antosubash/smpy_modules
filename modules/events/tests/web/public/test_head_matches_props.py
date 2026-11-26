"""The server head and the page's ``head`` prop are one resolution (#461).

Hydration replaces each keyed server tag with the client's. The client renders only the page's
props (``PublicHead`` reads ``head``, ``alternates``, ``json_ld`` and ``locale``), so if every
keyed server tag equals those values the replacement changes nothing; a difference here is a tag
that flips (or vanishes) the moment the script runs.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser

import pytest

from tests.support.public import INERTIA
from tests.web.public.test_event_page_details import mutate, text_of
from tests.web.public.test_index_pages import fx  # noqa: F401  (fixture)


class _Head(HTMLParser):
    """The elements of ``<head>`` as ``(tag, attrs, text)``; the first ``<head>`` only."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, dict[str, str], str]] = []
        self._open: list[str] | None = None
        self._in_head = False
        self._done = False

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self._in_head = True
        elif self._in_head and not self._done:
            self.items.append((tag, {k: v or "" for k, v in attrs}, ""))
            self._open = [tag]

    def handle_data(self, data):
        if self._open and self._in_head:
            tag, attrs, text = self.items[-1]
            self.items[-1] = (tag, attrs, text + data)

    def handle_endtag(self, tag):
        if tag == "head":
            self._in_head = False
            self._done = True
        elif self._open:
            self._open = None


def _server(html: str) -> tuple[str, dict[str, tuple[dict[str, str], str]]]:
    parser = _Head()
    parser.feed(html)
    title = next(text for tag, _, text in parser.items if tag == "title")
    keyed = {a["data-inertia"]: (a, text) for _, a, text in parser.items if "data-inertia" in a}
    assert len({a["data-inertia"] for _, a, _ in parser.items if "data-inertia" in a}) == len(keyed)
    return title, keyed


async def _check(client, path: str, *, event: bool) -> None:
    html = (await client.get(path)).text
    p = (await client.get(path, headers=INERTIA)).json()["props"]
    head = p["head"]
    title, keyed = _server(html)

    def content(key):
        return keyed[key][0]["content"] if key in keyed else None

    expected: dict[str, str] = {"og:title": head["title"], "og:type": "website"}
    expected["og:locale"] = p["locale"]
    for key, value in (
        ("description", head["description"]),
        ("og:description", head["description"]),
        ("og:url", head["canonical"]),
        ("og:image", head["image"]),
        ("robots", head["robots"]),
    ):
        if value:
            expected[key] = value
    if event:
        expected["twitter:card"] = "summary_large_image" if head["image"] else "summary"
        if head["image"]:
            expected["twitter:image"] = head["image"]
    assert title == head["title"] or title.replace("&amp;", "&") == head["title"]
    assert {key: content(key) for key in expected} == expected
    meta = {k for k, (a, _) in keyed.items() if "content" in a}
    assert meta == set(expected), (path, meta ^ set(expected))
    if head["canonical"]:
        assert keyed["canonical"][0]["href"] == head["canonical"]
    else:
        assert "canonical" not in keyed
    for entry in p["alternates"]:
        link = keyed[f"hreflang-{entry['locale']}"][0]
        assert (link["hreflang"], link["href"]) == (entry["locale"], entry["url"])
    if head["feed_url"]:
        assert keyed["feed"][0]["href"] == head["feed_url"]
    else:
        assert "feed" not in keyed
    expected_links = {"canonical", "feed"} | {f"hreflang-{a['locale']}" for a in p["alternates"]}
    assert set(keyed) == meta | (expected_links & set(keyed)) | (
        {"json-ld"} if p.get("json_ld") else set()
    )
    if p.get("json_ld"):
        assert json.loads(keyed["json-ld"][1]) == p["json_ld"]


async def _set_text(client, event, **fields):
    async def apply(db):
        text = await text_of(db, event.id)
        for name, value in fields.items():
            setattr(text, name, value)

    await mutate(client, apply)


EVENT_VARIANTS = {
    "seo": {"seo_title": "SEO & title", "seo_description": 'Seo "description"', "summary": "S"},
    "summary": {"seo_title": None, "seo_description": None, "summary": "A summary"},
    "description_only": {
        "seo_title": None, "seo_description": None, "summary": None, "description": "Plain words",
    },
    "nothing": {"seo_title": None, "seo_description": None, "summary": None, "description": ""},
}  # fmt: skip


@pytest.mark.parametrize("variant", EVENT_VARIANTS)
async def test_event_head_equals_its_props(public_locales_client, fx, variant):  # noqa: F811
    await _set_text(public_locales_client, fx.one_off, **EVENT_VARIANTS[variant])
    path = f"/events/{fx.slug(fx.one_off)}"
    await _check(public_locales_client, path, event=True)
    head = (await public_locales_client.get(path, headers=INERTIA)).json()["props"]["head"]
    assert head["description"], "an event always has a description (generated if need be)"


async def test_a_hidden_from_search_event_mirrors_its_robots(public_locales_client, fx):  # noqa: F811
    await _set_text(public_locales_client, fx.one_off, noindex=True)
    await _check(public_locales_client, f"/events/{fx.slug(fx.one_off)}", event=True)


async def test_the_german_event_page(public_locales_client, fx):  # noqa: F811
    await _check(public_locales_client, f"/de/events/{fx.slug(fx.one_off, 'de')}", event=True)


async def test_listing_heads_equal_their_props(public_locales_client, fx):  # noqa: F811
    paths = [
        "/events/",
        "/de/events/",
        f"/events/c/{fx.pub.slug}",
        f"/events/?category={fx.public_cat.slug}",
        "/events/?view=calendar",
    ]
    for path in paths:
        await _check(public_locales_client, path, event=False)
