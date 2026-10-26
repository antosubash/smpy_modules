"""The news section across hosts, bundle generations and failures (#80).

A host without news restores the pages and keeps the section unread; a bundle
written before news joined leaves the articles alone; a failure in news' apply
rolls pagebuilder's part back too; and the ``pre_restore`` snapshot carries
the articles, so a restore can itself be undone.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from bundle_app import (
    PAGES,
    approve,
    article,
    bundle_dir,
    bundle_host,
    download,
    news_files,
    restore,
    rezip,
    session,
    stage,
    take,
    upload,
)
from news.integrations.bundle import taxonomy
from news.models import NewsArticle
from pagebuilder.models import ContentSnapshot, ImportStatus, SnapshotSource
from sqlalchemy import delete
from sqlmodel import select

pytestmark = pytest.mark.asyncio


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


async def _retitle(client, slug: str, title: str) -> None:
    async with session(client) as db:
        row = (await db.execute(select(NewsArticle).where(NewsArticle.slug == slug))).scalar_one()
        row.title = title
        await db.commit()


async def test_a_host_without_news_restores_pages_and_keeps_the_section(tmp_path):
    async with bundle_host(tmp_path / "a") as source:
        await _page(source, "home", "Home")
        await article(source, "launch", title="From the source")
        data = await download(source, (await take(source))["id"])

    async with bundle_host(tmp_path / "b", news=False) as target:
        # On Postgres both hosts are windows onto one database: start empty.
        async with session(target) as db:
            await db.execute(delete(NewsArticle))
            await db.commit()
        await article(target, "local", title="Local")
        uploaded = await upload(target, data)
        assert uploaded.status_code == 201, uploaded.text

        plan = await restore(target, uploaded.json()["id"])

        assert plan["skipped"] == [{"section": "news", "version": 1}]
        assert (plan["sections"], plan["absent"]) == ([], [])
        pages = (await target.get(PAGES)).json()["items"]
        assert [p["slug"] for p in pages] == ["home"]
        assert await _titles(target) == {"local": "Local"}
        again = zipfile.ZipFile(io.BytesIO(await download(target, uploaded.json()["id"])))
        original = zipfile.ZipFile(io.BytesIO(data))
        assert again.read("news/articles/launch.json") == original.read("news/articles/launch.json")


@pytest.mark.parametrize("generation", ["minor-2-without-news", "minor-1"])
async def test_a_bundle_from_before_news_leaves_articles_alone(tmp_path, generation):
    async with bundle_host(tmp_path / "old", news=False) as old_host:
        await _page(old_host, "home", "Home")
        snapshot = await take(old_host)
        data = await download(old_host, snapshot["id"])
    if generation == "minor-1":
        manifest = dict(snapshot["manifest"], format_minor=1)
        manifest["contents"] = [
            {k: v for k, v in e.items() if k != "counts"} for e in manifest["contents"]
        ]
        data = rezip(data, {"manifest.json": manifest})

    async with bundle_host(tmp_path / "new") as host:
        await article(host, "live", title="Live")
        uploaded = await upload(host, data)
        assert uploaded.status_code == 201, uploaded.text

        plan = await restore(host, uploaded.json()["id"])

        assert plan["sections"] == [] and plan["skipped"] == []
        assert plan["absent"] == [{"section": "news", "label_key": "news.bundle.title"}]
        assert await _titles(host) == {"live": "Live"}


async def test_a_failure_in_news_rolls_back_pagebuilder_and_stays_pending(tmp_path, monkeypatch):
    async with bundle_host(tmp_path) as client:
        page = await _page(client, "home", "Before")
        await article(client, "launch", title="Original")
        snapshot = await take(client)
        await client.put(f"{PAGES}/{page['id']}", json={"title": "After"})
        await _retitle(client, "launch", "Edited")
        staged = await stage(client, snapshot["id"])
        assert staged.status_code == 201, staged.text

        async def boom(*args, **kwargs):
            raise RuntimeError("injected failure in news")

        # After the articles were written and flushed, so there is news to undo too.
        monkeypatch.setattr(taxonomy, "rebuild_tag_redirects", boom)
        with pytest.raises(RuntimeError, match="injected failure in news"):
            await approve(client, staged.json()["id"])

        assert (await client.get(f"{PAGES}/{page['id']}")).json()["title"] == "After"
        assert await _titles(client) == {"launch": "Edited"}
        pending = (await client.get("/api/pagebuilder/imports/pending")).json()
        assert (pending["id"], pending["status"]) == (
            staged.json()["id"],
            ImportStatus.PENDING.value,
        )
        async with session(client) as db:
            result = await db.execute(
                select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
            )
            assert result.scalars().all() == []
        root = bundle_dir(client, snapshot["id"]).parent
        assert sorted(p.name for p in root.iterdir()) == [str(snapshot["id"])]


async def test_the_pre_restore_snapshot_carries_news_so_a_restore_can_be_undone(tmp_path):
    async with bundle_host(tmp_path) as client:
        await article(client, "launch", title="Original")
        snapshot = await take(client)
        await _retitle(client, "launch", "Edited")
        await article(client, "fresh", title="Fresh")

        await restore(client, snapshot["id"])
        assert await _titles(client) == {"launch": "Original", "fresh": "Fresh"}

        async with session(client) as db:
            result = await db.execute(
                select(ContentSnapshot).where(ContentSnapshot.source == SnapshotSource.PRE_RESTORE)
            )
            pre = result.scalar_one()
        sections = {e["section"]: e for e in pre.manifest["contents"]}
        assert sections["news"]["counts"]["articles"] == 2
        assert news_files(client, pre.id)["articles/launch.json"]["title"] == "Edited"

        await restore(client, pre.id)
        assert await _titles(client) == {"launch": "Edited", "fresh": "Fresh"}
