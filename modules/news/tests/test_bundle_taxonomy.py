"""Categories and tags are restored by the name the admin compares, case-insensitively (#80).

``category_service`` and ``tag_service`` treat ``Updates`` and ``updates`` as
one name; a restore must not create the second row the admin would refuse.
"""

from __future__ import annotations

import pytest
from bundle_app import (
    add,
    approve,
    article,
    bundle_host,
    plan_lines,
    restore,
    session,
    stage,
    take,
    update,
)
from news.models import NewsArticle, NewsCategory, NewsTag
from sqlmodel import select

pytestmark = pytest.mark.asyncio


async def _rows(client, model) -> list:
    async with session(client) as db:
        return list((await db.execute(select(model))).scalars())


async def test_a_category_differing_only_in_case_lands_on_the_live_row(tmp_path):
    async with bundle_host(tmp_path) as client:
        [row] = await add(client, NewsCategory(name="Updates", slug="announcements", position=3))
        snapshot = await take(client)
        await update(client, NewsCategory, row.id, name="updates", slug="updates", position=0)
        # An article outside the bundle uses the live spelling.
        await article(client, "later", category="updates")

        plan = await restore(client, snapshot["id"])

        assert plan_lines(plan)["categories"]["count"] == 1
        [live] = await _rows(client, NewsCategory)
        assert (live.id, live.name, live.slug, live.position) == (
            row.id,
            "Updates",
            "announcements",
            3,
        )
        # Carried with the rename, as the categories screen's rename does.
        [later] = await _rows(client, NewsArticle)
        assert later.category == "Updates"


async def test_a_tag_differing_only_in_case_lands_on_the_live_row(tmp_path):
    async with bundle_host(tmp_path) as client:
        [tag] = await add(client, NewsTag(name="Python", slug="python"))
        snapshot = await take(client)
        await update(client, NewsTag, tag.id, name="PYTHON")

        await restore(client, snapshot["id"])

        assert [(t.id, t.name, t.slug) for t in await _rows(client, NewsTag)] == [
            (tag.id, "Python", "python")
        ]


@pytest.mark.parametrize("when", ["staging", "approval"])
async def test_two_live_names_matching_only_by_case_are_a_409(tmp_path, when):
    async with bundle_host(tmp_path) as client:
        [row] = await add(client, NewsCategory(name="Updates", slug="updates"))
        snapshot = await take(client)

        async def make_ambiguous() -> None:
            await update(client, NewsCategory, row.id, name="UPDATES")
            await add(client, NewsCategory(name="updates", slug="other"))

        if when == "staging":
            await make_ambiguous()
            refused = await stage(client, snapshot["id"])
        else:
            staged = await stage(client, snapshot["id"])
            assert staged.status_code == 201, staged.text
            await make_ambiguous()
            refused = await approve(client, staged.json()["id"])

        assert refused.status_code == 409
        assert "matches 2 category names here (UPDATES, updates)" in refused.json()["detail"]
        assert sorted(c.name for c in await _rows(client, NewsCategory)) == ["UPDATES", "updates"]
