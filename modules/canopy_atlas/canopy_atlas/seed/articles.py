"""Seed GCA's news articles, when the news module is installed.

``canopy_atlas`` does not depend on ``news``: a host that installs only the
atlas keeps the hand-authored ArticleCards on its home page. The seed probes
the news API and only swaps in a live feed when something answers.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

import httpx

from canopy_atlas.seed.uploads import rewrite_asset_paths

CONTENT_DIR = files("canopy_atlas") / "seed" / "content"

ARTICLES_API = "/api/news/articles"
FEED_BLOCK = "NewsFeed"
CARDS_BLOCK = "ArticleCards"
# The home page's news strip and the news index both become live feeds; the
# "Data highlights from selected GCA sites" strip stays hand-authored, because
# those are site highlights rather than articles.
FEED_BLOCK_IDS = ("news", "news-list")


def news_is_installed(client: httpx.Client, base_url: str) -> bool:
    response = client.get(
        f"{base_url}{ARTICLES_API}", headers={"Accept": "application/json"}
    )
    return response.status_code < 400


def _page_payload(article: dict[str, Any], uploads: dict[str, str]) -> dict[str, Any]:
    cover = rewrite_asset_paths(article["cover_image"], uploads)
    return {
        "title": article["title"],
        "slug": article["slug"],
        # The listing reads the excerpt and cover straight off the page, so
        # there is nothing to duplicate in the sidecar row.
        "meta_description": article["excerpt"],
        "og_image": cover,
        "draft_data": {
            "root": {"props": {"title": article["title"], "width": "full"}},
            "content": [
                {
                    "type": "PageHeader",
                    "props": {
                        "id": "ph",
                        "eyebrow": article["category"],
                        "title": article["title"],
                        "description": article["excerpt"],
                        "ctaLabel": "",
                        "ctaHref": "",
                    },
                }
            ],
            "zones": {},
        },
    }


def seed_articles(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    uploads: dict[str, str],
    *,
    publish: bool,
) -> int:
    """Publish each article's page and attach its metadata. Idempotent by slug."""
    articles = json.loads((CONTENT_DIR / "_articles.json").read_text())

    existing_pages = client.get(
        f"{base_url}/api/pagebuilder/pages", headers={"Accept": "application/json"}
    ).json()
    by_slug = {page["slug"]: page["id"] for page in existing_pages.get("items", [])}

    attached = client.get(
        f"{base_url}{ARTICLES_API}", params={"limit": 100}, headers={"Accept": "application/json"}
    ).json()
    already = {item["page_id"] for item in attached.get("items", [])}

    seeded = 0
    for article in articles:
        payload = _page_payload(article, uploads)
        slug = article["slug"]
        if slug in by_slug:
            page_id = by_slug[slug]
            response = client.put(
                f"{base_url}/api/pagebuilder/pages/{page_id}", json=payload, headers=headers
            )
        else:
            response = client.post(
                f"{base_url}/api/pagebuilder/pages", json=payload, headers=headers
            )
            page_id = response.json().get("id") if response.status_code < 400 else None
        if response.status_code >= 400 or page_id is None:
            print(f"  article {slug}: FAILED ({response.status_code})")
            continue

        if publish:
            client.post(
                f"{base_url}/api/pagebuilder/pages/{page_id}/publish",
                json={"note": "GCA seed"},
                headers=headers,
            )

        if page_id not in already:
            client.post(
                f"{base_url}{ARTICLES_API}",
                json={
                    "page_id": page_id,
                    "category": article["category"],
                    "published_at": article["published_at"],
                },
                headers=headers,
            )
        seeded += 1

    return seeded


def use_live_feed(data: dict[str, Any]) -> dict[str, Any]:
    """Swap a page's hand-authored ArticleCards for a live NewsFeed block.

    Applied to the payload on its way out rather than to the stored JSON, so a
    host without the news module still seeds the original content.
    """
    for block in data.get("content", []):
        if block.get("type") != CARDS_BLOCK:
            continue
        props = block.get("props", {})
        if props.get("id") not in FEED_BLOCK_IDS:
            continue
        block["type"] = FEED_BLOCK
        block["props"] = {
            "id": props["id"],
            "title": props.get("title", ""),
            "category": "",
            "limit": len(props.get("items", [])) or 4,
            "columns": props.get("columns", "4"),
            "viewAllLabel": props.get("viewAllLabel", ""),
            "viewAllHref": props.get("viewAllHref", ""),
        }
    return data
