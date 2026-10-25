"""A staged restore shows news' rows only to readers allowed to see them (#80).

The plan stored on the import (audited, served to all of Import / Export)
holds news' counts and nothing that names an article; the titles and slugs
are served back only to a reader holding ``news.edit``.
"""

from __future__ import annotations

import json

import pytest
from bundle_app import (
    PAGES,
    add,
    approve,
    article,
    as_role,
    bundle_host,
    plan_lines,
    session,
    stage,
    take,
    update,
)
from news.models import NewsArticle, NewsCategory
from pagebuilder.models import PendingImport

pytestmark = pytest.mark.asyncio

_PENDING = "/api/pagebuilder/imports/pending"
_REVIEW = "/pagebuilder/content/review"
_SECRET = "Unannounced merger"


async def _stored(client, import_id: int) -> dict:
    async with session(client) as db:
        return (await db.get(PendingImport, import_id)).plan


async def _staged_with_news(client) -> dict:
    row = await article(client, "merger", title=_SECRET)
    gone = await article(client, "recreated", title="Deleted since")
    snapshot = await take(client)
    async with session(client) as db:
        (await db.get(NewsArticle, row.id)).title = "Edited"
        await db.delete(await db.get(NewsArticle, gone.id))
        await db.commit()
    await article(client, "later-piece", title="Written after the snapshot")
    staged = await stage(client, snapshot["id"])  # by an admin
    assert staged.status_code == 201, staged.text
    return staged.json()


async def test_the_stored_plan_names_no_article(tmp_path):
    async with bundle_host(tmp_path) as client:
        staged = await _staged_with_news(client)
        # The stager may see news: their own response has the rows.
        assert plan_lines(staged["plan"])["overwritten"]["items"][0]["title"] == _SECRET

        stored = json.dumps(await _stored(client, staged["id"]))
        for text in (_SECRET, "merger", "Deleted since", "Written after the snapshot"):
            assert text not in stored
        [news] = json.loads(stored)["sections"]
        counts = {line["label_key"].rsplit(".", 1)[1]: line["count"] for line in news["lines"]}
        assert (counts["overwritten"], counts["new"], counts["untouched"]) == (1, 1, 1)

        applied = await approve(client, staged["id"])
        assert applied.status_code == 200, applied.text
        # The apply's own record: identities and counts, never a slug or title.
        audit = await _stored(client, staged["id"])
        assert set(audit["applied"]["news"]) == {"created", "overwritten", "category_respelled"}
        assert all(set(i) == {"id", "created_at"} for i in audit["applied"]["news"]["overwritten"])
        assert _SECRET not in json.dumps(audit) and "merger" not in json.dumps(audit)


@pytest.mark.parametrize("route", ["pending", "review", "reject"])
async def test_a_reader_without_news_edit_gets_counts_only(tmp_path, route):
    async with bundle_host(tmp_path) as client:
        staged = await _staged_with_news(client)
        reader = as_role("pb")
        if route == "pending":
            plan = (await client.get(_PENDING, headers=reader)).json()["plan"]
        elif route == "review":
            response = await client.get(_REVIEW, headers={**reader, "X-Inertia": "true"})
            plan = response.json()["props"]["pending"]["plan"]
        else:
            response = await client.post(
                f"/api/pagebuilder/imports/{staged['id']}/reject", headers=reader
            )
            assert response.status_code == 200, response.text
            plan = response.json()["plan"]

        [news] = plan["sections"]
        assert news["redacted"] is True
        assert news["reason_key"] == "pagebuilder.plan.section_redacted"
        assert news["permissions"] == ["news.edit"]
        assert plan_lines(plan)["overwritten"]["count"] == 1
        assert all(line["items"] == [] for line in news["lines"])
        assert _SECRET not in json.dumps(plan)

        # A reader who may see news gets the rows back.
        full = (await client.get(_PENDING, headers=as_role("pb-news-edit"))).json()
        if route != "reject":
            assert plan_lines(full["plan"])["overwritten"]["items"][0]["title"] == _SECRET


async def test_the_pending_import_needs_the_snapshot_permission(tmp_path):
    async with bundle_host(tmp_path) as client:
        await _staged_with_news(client)
        refused = await client.get(_PENDING, headers=as_role("news-only"))
        assert refused.status_code == 403


async def test_a_section_denied_at_staging_cannot_block_the_approval(tmp_path):
    async with bundle_host(tmp_path) as client:
        page = (
            await client.post(PAGES, json={"title": "Before", "slug": "home", "draft_data": {}})
        ).json()
        row = await article(client, "launch", translation_group="g1")
        snapshot = await take(client)
        await client.put(f"{PAGES}/{page['id']}", json={"title": "After"})
        staged = await stage(client, snapshot["id"], as_role("pb"))
        assert staged.json()["plan"]["denied"][0]["section"] == "news"
        # News now conflicts (another article took the address) — but news is
        # not being restored, so the pages must still go through.
        await update(client, NewsArticle, row.id, slug="launch-old")
        await article(client, "launch", translation_group="g2")

        applied = await approve(client, staged.json()["id"])

        assert applied.status_code == 200, applied.text
        assert [d["section"] for d in applied.json()["denied_sections"]] == ["news"]
        assert (await client.get(f"{PAGES}/{page['id']}")).json()["title"] == "Before"


async def test_a_category_respelling_outside_the_bundle_is_disclosed(tmp_path):
    async with bundle_host(tmp_path) as client:
        [category] = await add(client, NewsCategory(name="Updates", slug="updates"))
        await article(client, "bundled", category="Updates")
        snapshot = await take(client)
        await update(client, NewsCategory, category.id, name="updates")
        async with session(client) as db:
            bundled = (await db.execute(NewsArticle.__table__.select())).first()
            row = await db.get(NewsArticle, bundled.id)
            row.category = "updates"
            await db.commit()
        outside = await article(client, "outside", category="updates", title="Outside")

        staged = await stage(client, snapshot["id"])
        line = plan_lines(staged.json()["plan"])["category_respelled"]
        assert (line["count"], line["tone"]) == (1, "warning")
        assert [i["slug"] for i in line["items"]] == ["outside"]
        applied = await approve(client, staged.json()["id"])

        assert applied.json()["sections"]["news"]["category_respelled"] == 1
        audit = await _stored(client, staged.json()["id"])
        assert [i["id"] for i in audit["applied"]["news"]["category_respelled"]] == [outside.id]
        async with session(client) as db:
            assert (await db.get(NewsArticle, outside.id)).category == "Updates"
