"""Article seeding is optional: canopy_atlas must not depend on news."""

from __future__ import annotations

import httpx
from canopy_atlas.seed.articles import news_is_installed, use_live_feed


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")


def test_detects_a_host_without_the_news_module():
    assert not news_is_installed(_client(lambda request: httpx.Response(404)), "http://t")


def test_detects_a_host_with_the_news_module():
    def handler(request):
        return httpx.Response(200, json={"items": [], "total": 0})

    assert news_is_installed(_client(handler), "http://t")


def _home(block_id: str):
    return {
        "content": [
            {
                "type": "ArticleCards",
                "props": {
                    "id": block_id,
                    "title": "Latest news",
                    "columns": "4",
                    "viewAllLabel": "View all",
                    "viewAllHref": "/p/news-index",
                    "items": [{"title": "a"}, {"title": "b"}],
                },
            }
        ]
    }


def test_swaps_the_news_strip_for_a_live_feed():
    out = use_live_feed(_home("news"))
    block = out["content"][0]
    assert block["type"] == "NewsFeed"
    assert block["props"]["title"] == "Latest news"
    # The card count becomes the feed's limit, so the layout is unchanged.
    assert block["props"]["limit"] == 2
    assert block["props"]["viewAllHref"] == "/p/news-index"


def test_leaves_other_article_strips_alone():
    # "Data highlights from selected GCA sites" is site highlights, not
    # articles — it stays hand-authored.
    out = use_live_feed(_home("sites"))
    assert out["content"][0]["type"] == "ArticleCards"
