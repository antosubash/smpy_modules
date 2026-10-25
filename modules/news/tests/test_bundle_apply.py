"""How a restored ``news/`` section lands on the articles already there (#80).

Matching goes through pagebuilder's own ``match_by_identity``: translation
group first, then ``(locale, slug)``, trashed rows included. These drive the
real staging and approval endpoints against a stored snapshot whose live rows
moved since it was taken.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from bundle_app import add, approve, article, bundle_dir, bundle_host, restore, session, stage, take
from news.models import (
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleTag,
    NewsCategory,
    NewsTag,
    NewsTagRedirect,
)
from pagebuilder.models import PendingImport
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def _articles(client) -> dict[tuple[str, str], NewsArticle]:
    async with session(client) as db:
        rows = (await db.execute(select(NewsArticle))).scalars().all()
    return {(r.locale, r.slug): r for r in rows}


async def _update(client, model, row_id, **fields) -> None:
    async with session(client) as db:
        row = await db.get(model, row_id)
        for name, value in fields.items():
            setattr(row, name, value)
        await db.commit()


def _lines(plan: dict) -> dict[str, dict]:
    [news] = plan["sections"]
    return {line["label_key"].rsplit(".", 1)[1]: line for line in news["lines"]}


async def _redirects(client) -> set[tuple[str, str, int]]:
    async with session(client) as db:
        rows = (await db.execute(select(NewsArticleRedirect))).scalars().all()
    return {(r.locale, r.from_slug, r.article_id) for r in rows}


async def test_a_renamed_article_moves_back_and_keeps_a_redirect(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", translation_group="g1", title="Original")
        snapshot = await take(client)
        await _update(client, NewsArticle, row.id, slug="launch-v2", title="Edited")
        await add(client, NewsArticleRedirect(from_slug="launch", locale="en", article_id=row.id))

        plan = await restore(client, snapshot["id"])

        lines = _lines(plan)
        assert lines["renamed_from"]["items"][0]["slug"] == "launch"
        assert (lines["overwritten"]["count"], lines["new"]["count"]) == (1, 0)
        assert plan["sections"][0]["overwrites"] == 1
        live = await _articles(client)
        assert list(live) == [("en", "launch")]
        assert (live[("en", "launch")].id, live[("en", "launch")].title) == (row.id, "Original")
        # The address it was renamed to keeps working; the old one is its own again.
        assert await _redirects(client) == {("en", "launch-v2", row.id)}


async def test_an_article_found_by_address_keeps_its_own_group(tmp_path):
    async with bundle_host(tmp_path) as client:
        await article(client, "about", translation_group="g-snapshot", title="Snapshot")
        snapshot = await take(client)
        async with session(client) as db:
            old = (await db.execute(select(NewsArticle))).scalar_one()
            await db.delete(old)
            await db.commit()
        made_here = await article(client, "about", translation_group="g-live", title="Live")

        await restore(client, snapshot["id"])

        [row] = (await _articles(client)).values()
        assert (row.id, row.title, row.translation_group) == (made_here.id, "Snapshot", "g-live")


async def test_a_trashed_match_is_revived(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "notice", translation_group="g1")
        snapshot = await take(client)
        await _update(client, NewsArticle, row.id, deleted_at=datetime.now(UTC))

        plan = await restore(client, snapshot["id"])

        assert _lines(plan)["revived"]["count"] == 1
        live = (await _articles(client))[("en", "notice")]
        assert (live.id, live.deleted_at) == (row.id, None)


async def test_an_address_another_article_took_is_a_409_at_staging(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", translation_group="g1")
        snapshot = await take(client)
        await _update(client, NewsArticle, row.id, slug="launch-old")
        await article(client, "launch", translation_group="g2", title="Someone else")

        refused = await stage(client, snapshot["id"])

        assert refused.status_code == 409
        assert "different article" in refused.json()["detail"]


@pytest.mark.parametrize("kind", ["category", "tag"])
async def test_a_slug_held_by_another_category_or_tag_is_a_409(tmp_path, kind):
    model = NewsCategory if kind == "category" else NewsTag
    async with bundle_host(tmp_path) as client:
        [row] = await add(client, model(name="News", slug="news"))
        snapshot = await take(client)
        await _update(client, model, row.id, name="Announcements")

        refused = await stage(client, snapshot["id"])

        assert refused.status_code == 409
        assert f"{kind} slug 'news' now belongs to 'Announcements'" in refused.json()["detail"]


async def test_a_conflict_arising_after_staging_is_a_409_at_approval(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", translation_group="g1", title="Original")
        snapshot = await take(client)
        await _update(client, NewsArticle, row.id, title="Edited")
        staged = await stage(client, snapshot["id"])
        assert staged.status_code == 201, staged.text
        await _update(client, NewsArticle, row.id, slug="launch-old")
        await article(client, "launch", translation_group="g2", title="Someone else")

        refused = await approve(client, staged.json()["id"])

        assert refused.status_code == 409
        live = await _articles(client)
        assert live[("en", "launch-old")].title == "Edited"
        assert live[("en", "launch")].title == "Someone else"
        async with session(client) as db:
            pending = await db.get(PendingImport, staged.json()["id"])
        assert pending.status.value == "pending"


async def test_tag_links_are_replaced_only_for_bundled_articles(tmp_path):
    async with bundle_host(tmp_path) as client:
        python, extra = await add(
            client, NewsTag(name="Python", slug="python"), NewsTag(name="Extra", slug="extra")
        )
        bundled = await article(client, "a")
        await add(client, NewsArticleTag(article_id=bundled.id, tag_id=python.id))
        snapshot = await take(client)
        later = await article(client, "b")
        await add(
            client,
            NewsArticleTag(article_id=bundled.id, tag_id=extra.id),
            NewsArticleTag(article_id=later.id, tag_id=extra.id),
        )

        plan = await restore(client, snapshot["id"])

        assert _lines(plan)["untouched"]["items"][0]["slug"] == "b"
        async with session(client) as db:
            links = (await db.execute(select(NewsArticleTag))).scalars().all()
        assert {(link.article_id, link.tag_id) for link in links} == {
            (bundled.id, python.id),
            (later.id, extra.id),
        }


async def test_an_unresolvable_redirect_is_dropped_and_reported(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "kept")
        snapshot = await take(client)
        redirects = bundle_dir(client, snapshot["id"]) / "news" / "redirects.json"
        redirects.write_text(
            json.dumps(
                [
                    {"from_slug": "gone", "locale": "en", "to_slug": "missing"},
                    {"from_slug": "older", "locale": "en", "to_slug": "kept"},
                ]
            )
        )

        staged = await stage(client, snapshot["id"])
        dropped = _lines(staged.json()["plan"])["redirects_dropped"]
        assert (dropped["count"], dropped["tone"]) == (1, "warning")
        assert (await approve(client, staged.json()["id"])).status_code == 200

        assert await _redirects(client) == {("en", "older", row.id)}
        async with session(client) as db:
            audit = await db.get(PendingImport, staged.json()["id"])
        assert audit.plan["applied"]["news"]["redirects_dropped"] == [
            {"locale": "en", "from_slug": "gone"}
        ]


async def test_an_absent_field_leaves_the_live_value(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", author="Snapshot Author", title="Original")
        snapshot = await take(client)
        doc_path = bundle_dir(client, snapshot["id"]) / "news" / "articles" / "launch.json"
        doc = json.loads(doc_path.read_text())
        del doc["author"]
        doc_path.write_text(json.dumps(doc))
        await _update(client, NewsArticle, row.id, author="Live Author", title="Edited")

        await restore(client, snapshot["id"])

        live = (await _articles(client))[("en", "launch")]
        assert (live.title, live.author) == ("Original", "Live Author")


async def test_a_renamed_tag_moves_back_and_keeps_a_tag_redirect(tmp_path):
    async with bundle_host(tmp_path) as client:
        [tag] = await add(client, NewsTag(name="Python", slug="python"))
        snapshot = await take(client)
        await _update(client, NewsTag, tag.id, slug="python3")

        await restore(client, snapshot["id"])

        async with session(client) as db:
            live = await db.get(NewsTag, tag.id)
            rows = (await db.execute(select(NewsTagRedirect))).scalars().all()
        assert live.slug == "python"
        assert [(r.from_slug, r.tag_id) for r in rows] == [("python3", tag.id)]
