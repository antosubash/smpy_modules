"""The news section follows news' own permissions through Import / Export (#80).

News declares them (``capture_permissions = {news.edit}``,
``apply_permissions = {news.edit, news.publish}``); pagebuilder checks them
for the acting user with the framework's resolution. Pages are pagebuilder's
and restore regardless.
"""

from __future__ import annotations

import pytest
from bundle_app import (
    PAGES,
    approve,
    article,
    as_role,
    bundle_dir,
    bundle_host,
    news_files,
    session,
    stage,
    take,
    update,
)
from news.models import NewsArticle
from pagebuilder.models import ContentSnapshot, PendingImport, SnapshotSource
from sqlmodel import select

pytestmark = pytest.mark.asyncio

_DENIED = "pagebuilder.plan.section_denied"
_OMITTED = "pagebuilder.plan.section_omitted"
_RESTORE_NEEDS = ["news.edit", "news.publish"]


async def _page(client, slug: str, title: str) -> dict:
    response = await client.post(
        PAGES, json={"title": title, "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _titles(client) -> dict[str, str]:
    async with session(client) as db:
        rows = (await db.execute(select(NewsArticle))).scalars().all()
    return {r.slug: r.title for r in rows}


async def _pre_restore(client) -> ContentSnapshot:
    async with session(client) as db:
        result = await db.execute(
            select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
        )
        return result.scalar_one()


async def test_a_snapshot_by_someone_without_news_edit_leaves_news_out(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", title="Original")
        snapshot = await take(client, as_role("pb"))

        manifest = snapshot["manifest"]
        assert [e["section"] for e in manifest["contents"]] == ["pagebuilder"]
        assert manifest["omitted"] == [
            {
                "section": "news",
                "label_key": "news.bundle.title",
                "reason": "permission",
                "reason_key": _OMITTED,
                "permissions": ["news.edit"],
            }
        ]
        assert not (bundle_dir(client, snapshot["id"]) / "news").exists()

        # Restoring it later — by anyone — reads news as absent: nothing deleted.
        await update(client, NewsArticle, row.id, title="Edited")
        await article(client, "fresh", title="Fresh")
        staged = await stage(client, snapshot["id"])
        plan = staged.json()["plan"]
        assert plan["absent"] == [
            {
                "section": "news",
                "label_key": "news.bundle.title",
                "omitted": True,
                "reason_key": _OMITTED,
                "permissions": ["news.edit"],
            }
        ]
        assert (plan["sections"], plan["skipped"], plan["denied"]) == ([], [], [])
        assert (await approve(client, staged.json()["id"])).status_code == 200
        assert await _titles(client) == {"launch": "Edited", "fresh": "Fresh"}


async def test_a_snapshot_by_a_news_editor_carries_news(tmp_path):
    async with bundle_host(tmp_path) as client:
        await article(client, "launch")
        snapshot = await take(client, as_role("pb-news-edit"))
        assert "omitted" not in snapshot["manifest"]
        # This host's record of what downloading it takes (stored row only).
        assert snapshot["manifest"]["host_download_permissions"] == {"news": ["news.edit"]}
        assert "articles/launch.json" in news_files(client, snapshot["id"])


async def test_downloading_a_bundle_with_news_needs_news_edit(tmp_path):
    async with bundle_host(tmp_path) as client:
        await article(client, "launch")
        with_news = await take(client)
        without = await take(client, as_role("pb"))
        url = "/api/pagebuilder/snapshots/{}/download"

        refused = await client.get(url.format(with_news["id"]), headers=as_role("pb"))
        assert refused.status_code == 403
        assert refused.json() == {"detail": "Permission required: news.edit"}

        allowed = await client.get(url.format(with_news["id"]), headers=as_role("pb-news-edit"))
        assert allowed.status_code == 200
        # A bundle the capture left news out of is anyone's to download.
        assert (
            await client.get(url.format(without["id"]), headers=as_role("pb"))
        ).status_code == 200


async def test_a_stager_without_news_permissions_sees_the_warning_up_front(tmp_path):
    async with bundle_host(tmp_path) as client:
        page = await _page(client, "home", "Before")
        row = await article(client, "launch", title="Original")
        snapshot = await take(client)
        await client.put(f"{PAGES}/{page['id']}", json={"title": "After"})
        await update(client, NewsArticle, row.id, title="Edited")

        staged = await stage(client, snapshot["id"], as_role("pb"))

        plan = staged.json()["plan"]
        denied = [
            {
                "section": "news",
                "label_key": "news.bundle.title",
                "reason_key": _DENIED,
                "permissions": _RESTORE_NEEDS,
            }
        ]
        assert (plan["denied"], plan["sections"]) == (denied, [])  # no article is listed
        # Left out at staging stays out, even for an approver who could apply it.
        applied = await approve(client, staged.json()["id"])
        assert applied.status_code == 200, applied.text
        assert applied.json()["denied_sections"] == denied
        assert applied.json()["sections"] == {}
        assert (await client.get(f"{PAGES}/{page['id']}")).json()["title"] == "Before"
        assert await _titles(client) == {"launch": "Edited"}


@pytest.mark.parametrize(
    ("approver", "missing"), [("pb", _RESTORE_NEEDS), ("pb-news-edit", ["news.publish"])]
)
async def test_an_approver_without_news_permissions_restores_only_the_pages(
    tmp_path, approver, missing
):
    async with bundle_host(tmp_path) as client:
        page = await _page(client, "home", "Before")
        row = await article(client, "launch", title="Original")
        snapshot = await take(client)
        await client.put(f"{PAGES}/{page['id']}", json={"title": "After"})
        await update(client, NewsArticle, row.id, title="Edited")
        staged = await stage(client, snapshot["id"])  # by an admin: news is planned
        assert [s["section"] for s in staged.json()["plan"]["sections"]] == ["news"]

        applied = await approve(client, staged.json()["id"], as_role(approver))

        assert applied.status_code == 200, applied.text
        assert applied.json()["denied_sections"] == [
            {
                "section": "news",
                "label_key": "news.bundle.title",
                "reason_key": _DENIED,
                "permissions": missing,
            }
        ]
        assert (await client.get(f"{PAGES}/{page['id']}")).json()["title"] == "Before"
        assert await _titles(client) == {"launch": "Edited"}
        async with session(client) as db:
            audit = await db.get(PendingImport, staged.json()["id"])
        assert "news" not in audit.plan["applied"]
        assert audit.plan["denied"][0]["permissions"] == missing
        # The safety snapshot is the system's, not the approver's: news is in it.
        pre = await _pre_restore(client)
        assert "news" in {e["section"] for e in pre.manifest["contents"]}
        assert "omitted" not in pre.manifest


async def test_stager_and_approver_with_news_permissions_restore_news(tmp_path):
    async with bundle_host(tmp_path) as client:
        row = await article(client, "launch", title="Original")
        snapshot = await take(client, as_role("pb-news-edit"))
        await update(client, NewsArticle, row.id, title="Edited")

        staged = await stage(client, snapshot["id"], as_role("pb-news"))
        assert staged.json()["plan"]["denied"] == []
        applied = await approve(client, staged.json()["id"], as_role("pb-news"))

        assert applied.json()["denied_sections"] == []
        assert applied.json()["sections"]["news"]["overwritten"] == 1
        assert await _titles(client) == {"launch": "Original"}
