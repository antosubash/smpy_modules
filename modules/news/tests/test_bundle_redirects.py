"""Redirects a restore would make wrong are dropped and named in the plan (#80).

A bundled redirect from an address an article now holds would sit under that
article and start sending its readers elsewhere the day it is unpublished or
trashed; one from a slug a tag holds would do the same to the tag's archive.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from bundle_app import (
    add,
    approve,
    article,
    bundle_dir,
    bundle_host,
    plan_lines,
    session,
    stage,
    take,
)
from news.models import NewsArticleRedirect, NewsTag, NewsTagRedirect
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def _restore(client, snapshot_id: int) -> tuple[dict, dict]:
    """Stage and approve; ``(plan, the news counts the approval reported)``."""
    staged = await stage(client, snapshot_id)
    assert staged.status_code == 201, staged.text
    applied = await approve(client, staged.json()["id"])
    assert applied.status_code == 200, applied.text
    return staged.json()["plan"], applied.json()["sections"]["news"]


@pytest.mark.parametrize("holder", ["live", "trashed"])
async def test_a_redirect_from_an_address_an_article_holds_is_dropped(tmp_path, holder):
    async with bundle_host(tmp_path) as client:
        current = await article(client, "current")
        await add(client, NewsArticleRedirect(from_slug="old", locale="en", article_id=current.id))
        snapshot = await take(client)
        trashed = datetime.now(UTC) if holder == "trashed" else None
        await article(client, "old", title="Claimed the old address", deleted_at=trashed)

        plan, applied = await _restore(client, snapshot["id"])

        dropped = plan_lines(plan)["redirects_dropped"]
        assert (dropped["count"], dropped["tone"]) == (1, "warning")
        assert [(i["slug"], i["locale"]) for i in dropped["items"]] == [("old", "en")]
        assert applied["redirects_dropped"] == 1
        async with session(client) as db:
            assert (await db.execute(select(NewsArticleRedirect))).scalars().all() == []


async def test_the_same_address_in_another_language_does_not_count(tmp_path, bilingual):
    async with bundle_host(tmp_path) as client:
        current = await article(client, "current")
        await add(client, NewsArticleRedirect(from_slug="old", locale="en", article_id=current.id))
        snapshot = await take(client)
        await article(client, "old", locale="de")

        plan, _ = await _restore(client, snapshot["id"])

        assert plan_lines(plan)["redirects_dropped"]["count"] == 0
        async with session(client) as db:
            [row] = (await db.execute(select(NewsArticleRedirect))).scalars().all()
        assert (row.locale, row.from_slug, row.article_id) == ("en", "old", current.id)


async def test_dropped_tag_redirects_are_in_the_plan(tmp_path):
    async with bundle_host(tmp_path) as client:
        python, _ = await add(
            client, NewsTag(name="Python", slug="python"), NewsTag(name="Py", slug="py")
        )
        await add(client, NewsTagRedirect(from_slug="snake", tag_id=python.id))
        snapshot = await take(client)
        path = bundle_dir(client, snapshot["id"]) / "news" / "tag_redirects.json"
        path.write_text(
            json.dumps(
                [
                    {"from_slug": "snake", "to_slug": "python"},  # kept
                    {"from_slug": "py", "to_slug": "python"},  # a tag holds "py"
                    {"from_slug": "gone", "to_slug": "missing"},  # no such tag
                ]
            )
        )

        plan, applied = await _restore(client, snapshot["id"])

        dropped = plan_lines(plan)["redirects_dropped"]
        assert (dropped["count"], dropped["tone"]) == (2, "warning")
        assert sorted(i["slug"] for i in dropped["items"]) == ["gone", "py"]
        assert {i["note_key"] for i in dropped["items"]} == {"news.bundle.plan.tags"}
        assert applied["redirects_dropped"] == 2
        async with session(client) as db:
            rows = (await db.execute(select(NewsTagRedirect))).scalars().all()
        assert [(r.from_slug, r.tag_id) for r in rows] == [("snake", python.id)]
