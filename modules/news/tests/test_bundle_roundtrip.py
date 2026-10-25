"""Articles round-trip through pagebuilder's content bundle (#80).

The acceptance test of the news section: capture a site with articles in two
languages, categories, tags, media, a renamed article and a renamed tag; wipe
news; restore; capture again — and the ``news/`` documents come out identical,
with the trashed article absent from both.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from bundle_app import PNG_BYTES, add, article, bundle_host, news_files, restore, session, take
from news.models import (
    ArticleStatus,
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleRevision,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
    NewsTagRedirect,
)
from sqlalchemy import delete
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_WIPE = (
    NewsArticleTag,
    NewsArticleRedirect,
    NewsTagRedirect,
    NewsArticleRevision,
    NewsArticle,
    NewsTag,
    NewsCategory,
)


async def seed_site(client) -> dict:
    """A small bilingual archive with every kind of row the section carries."""
    uploaded = await client.post(
        "/api/pagebuilder/uploads", files={"file": ("hero.png", PNG_BYTES, "image/png")}
    )
    assert uploaded.status_code == 201, uploaded.text
    url = uploaded.json()["url"]
    python, release = await add(
        client, NewsTag(name="Python", slug="python"), NewsTag(name="Release", slug="release")
    )
    await add(client, NewsCategory(name="Updates", slug="updates", position=1))
    launch = await article(
        client,
        "launch",
        translation_group="g-launch",
        category="Updates",
        og_image=url,
        draft_data={"content": [{"type": "Image", "props": {"src": url}}]},
        published_data={"content": [{"type": "Image", "props": {"src": url}}]},
        status=ArticleStatus.PUBLISHED,
        published_at=datetime(2026, 5, 1, 9, 30, tzinfo=UTC),
        json_ld={"@type": "NewsArticle", "image": url},
        author="Ada Lovelace",
        pinned=True,
    )
    start = await article(client, "start", locale="de", translation_group="g-launch")
    moved = await article(client, "current", publish_at=datetime(2030, 1, 1, tzinfo=UTC))
    await article(client, "binned", deleted_at=datetime(2026, 6, 1, tzinfo=UTC))
    await add(
        client,
        NewsArticleTag(article_id=launch.id, tag_id=python.id),
        NewsArticleTag(article_id=launch.id, tag_id=release.id),
        NewsArticleTag(article_id=start.id, tag_id=python.id),
        NewsArticleRedirect(from_slug="previous", locale="en", article_id=moved.id),
        NewsTagRedirect(from_slug="py", tag_id=python.id),
    )
    return {"url": url}


async def wipe_news(client) -> None:
    async with session(client) as db:
        for model in _WIPE:
            await db.execute(delete(model))
        await db.commit()


async def test_capture_wipe_restore_capture_is_identical(tmp_path, bilingual):
    async with bundle_host(tmp_path) as client:
        seeded = await seed_site(client)
        first = await take(client)
        entry = {e["section"]: e for e in first["manifest"]["contents"]}["news"]
        assert entry == {
            "section": "news",
            "version": 1,
            "required": False,
            "paths": ["news/"],
            "counts": {"articles": 3, "categories": 1, "tags": 2, "redirects": 2},
        }
        before = news_files(client, first["id"])
        assert sorted(before) == [
            "articles/current.json",
            "articles/de__start.json",
            "articles/launch.json",
            "categories.json",
            "redirects.json",
            "tag_redirects.json",
            "tags.json",
        ]
        launch = before["articles/launch.json"]
        assert launch["og_image"] == "asset://hero.png"
        assert launch["json_ld"]["image"] == "asset://hero.png"
        assert launch["draft_data"]["content"][0]["props"]["src"] == "asset://hero.png"
        assert launch["tags"] == ["Python", "Release"]
        assert launch["published_at"] == "2026-05-01T09:30:00+00:00"
        assert "created_by" not in launch and "rejection_note" not in launch and "id" not in launch

        await wipe_news(client)
        plan = await restore(client, first["id"])
        [news] = plan["sections"]
        counts = {line["label_key"].rsplit(".", 1)[1]: line["count"] for line in news["lines"]}
        assert counts["new"] == 3 and counts["overwritten"] == 0

        second = await take(client)
        assert news_files(client, second["id"]) == before

        async with session(client) as db:
            rows = (await db.execute(select(NewsArticle))).scalars().all()
            assert sorted(r.slug for r in rows) == ["current", "launch", "start"]
            restored = next(r for r in rows if r.slug == "launch")
            assert restored.og_image == seeded["url"]
            assert restored.status == ArticleStatus.PUBLISHED
            start = next(r for r in rows if r.slug == "start")
            assert (start.locale, start.translation_group) == ("de", "g-launch")
            # No revision is written per restored article.
            assert (await db.execute(select(NewsArticleRevision))).scalars().all() == []
