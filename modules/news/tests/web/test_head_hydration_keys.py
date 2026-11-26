"""Every server tag has an equal, keyed client twin (#451, #462).

Titles are special: Inertia replaces the document title even without a key.
All other elements must be managed, or they survive a client-side visit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest
from news.core import settings as news_settings
from news.core.settings import NewsSettings
from news.web.endpoints.public import _head

from tests.support.factories import make_article

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


class Head(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.items = []
        self.feed(markup.split("</head>", 1)[0])

    def handle_starttag(self, tag, attrs):
        # The host injects its Vite module script; news owns only JSON-LD scripts.
        if tag == "script" and dict(attrs).get("type") != "application/ld+json":
            return
        if tag in {"meta", "link", "script", "title"}:
            self.items.append((tag, dict(attrs), ""))

    def handle_data(self, data):
        if self.items:
            tag, attrs, text = self.items[-1]
            self.items[-1] = (tag, attrs, text + data)

    def keyed(self):
        tags = [(tag, attrs, text) for tag, attrs, text in self.items if tag != "title"]
        assert all(attrs.get("data-inertia") for _, attrs, _ in tags), tags
        keyed = {attrs["data-inertia"]: (tag, attrs, text) for tag, attrs, text in tags}
        assert len(keyed) == len(tags), "duplicate key in the server head"
        return keyed


@pytest.mark.parametrize("article", [False, True])
def test_every_emitted_tag_is_managed(article):
    values = {
        "title": 'A "quoted" & title', "description": "Description",
        "canonical": "https://example.org/news/",
        "site_name": "Site", "locale": "en", "alternates": [
            {"locale": "en", "url": "https://example.org/news/"},
            {"locale": "de", "url": "https://example.org/de/news/"},
            {"locale": "x-default", "url": "https://example.org/news/"},
        ],
    }
    if article:
        markup = _head.article_head(
            **values, image="https://example.org/cover.png", twitter_handle="@site",
            published_at="2026-01-01", author="Ada", section="Trees", index_in_search=False,
            json_ld={"headline": "</script><!--"},
        )
    else:
        markup = _head.listing_head(**values, feed_url="https://example.org/news/feed.xml")
    keyed = Head(markup).keyed()
    required = {"canonical", "og:title", "og:type", "og:url", "og:locale", "hreflang-de"}
    assert required <= keyed.keys()


async def check_props(client, path, *, article):
    response = await client.get(path)
    assert response.status_code == 200
    props_response = await client.get(path, headers=INERTIA)
    assert props_response.status_code == 200
    h = props_response.json()["props"]["head"]
    parsed = Head(response.text)
    keyed = parsed.keyed()
    assert next(text for tag, _, text in parsed.items if tag == "title") == h["title"]
    expected = {"og:title": h["title"], "og:type": "article" if article else "website"}
    for key, value in (
        ("description", h["description"]), ("og:description", h["description"]),
        ("og:url", h["canonical"]), ("og:site_name", h["site_name"]),
        ("og:locale", h["locale"]),
        ("robots", "noindex,nofollow" if article and not h["index_in_search"] else h.get("robots")),
    ):
        if value:
            expected[key] = value
    if article:
        assert h["json_ld"] != {}, "an empty JSON-LD object must be omitted on both sides"
        expected["twitter:card"] = "summary_large_image" if h["image"] else "summary"
        for key, field in (
            ("og:image", "image"), ("twitter:image", "image"), ("twitter:site", "twitter_handle"),
            ("article:published_time", "published_at"), ("article:author", "author"),
            ("article:section", "section"),
        ):
            if h[field]:
                expected[key] = h[field]
    for a in h["alternates"] or []:
        if a["locale"] not in {h["locale"], "x-default"}:
            expected[f'og:locale:alternate-{a["locale"]}'] = a["locale"]
    meta = {k: attrs["content"] for k, (tag, attrs, _) in keyed.items() if tag == "meta"}
    assert meta == expected
    expected_keys = set(expected)
    if h["canonical"]:
        expected_keys.add("canonical")
        assert keyed["canonical"][1]["href"] == h["canonical"]
    for a in h["alternates"] or []:
        key = f'hreflang-{a["locale"]}'
        expected_keys.add(key)
        assert (keyed[key][1]["hreflang"], keyed[key][1]["href"]) == (a["locale"], a["url"])
    if h["feed_url"]:
        expected_keys.add("feed")
        assert keyed["feed"][1] == {
            "rel": "alternate", "type": "application/rss+xml", "data-inertia": "feed",
            "title": h["title"], "href": h["feed_url"],
        }
    if h.get("json_ld"):
        expected_keys.add("json-ld")
        assert json.loads(keyed["json-ld"][2]) == h["json_ld"]
    assert set(keyed) == expected_keys


@pytest.mark.asyncio
async def test_article_keys_and_values_equal_props(bilingual_public_client):
    client = bilingual_public_client
    async with client.db_state.session_factory() as db:
        article = await make_article(
            db, slug="keyed", title='Keyed & "quoted"', meta_description="d",
            og_image="/cover.png", category="News", author="Ada",
            published_at=datetime(2026, 1, 2, tzinfo=UTC), index_in_search=False,
        )
        article.json_ld = {"@type": "NewsArticle", "headline": "</script><!--"}
        db.add(article)
        await db.commit()
        await make_article(
            db, slug="schluessel", locale="de", translation_group=article.translation_group
        )
        minimal = await make_article(db, slug="minimal")
        minimal.json_ld = {}
        db.add(minimal)
        await db.commit()
    news_settings.use(NewsSettings(site_name="S", twitter_handle="@s", public_base_url="https://example.org"))
    try:
        for path in ("/news/keyed", "/de/news/schluessel", "/news/minimal"):
            await check_props(client, path, article=True)
    finally:
        news_settings.reset()


@pytest.mark.asyncio
async def test_archive_keys_and_values_equal_props(bilingual_public_client):
    client = bilingual_public_client
    async with client.db_state.session_factory() as db:
        for i in range(13):
            await make_article(db, slug=f"tree-{i}", title=f"Tree {i}")
        await db.commit()
    for path in ("/news/", "/news/?page=2", "/news/tag/trees", "/news/?q=tree", "/de/news/"):
        await check_props(client, path, article=False)
