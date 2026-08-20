"""Trash: soft delete, restore, purge, and the retention sweep.

The point of these is that "deleted" now means two different things, and the
difference has to hold everywhere at once. A trashed page must vanish from every
listing *and* from the public site immediately, while still being recoverable —
so the cases below check the disappearance and the recovery together rather than
either on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pagebuilder.models import Page
from pagebuilder.service import PagesService
from pagebuilder.service._trash import RETENTION_DAYS
from sqlmodel import select

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _create(client: AsyncClient, slug: str, *, publish: bool = False) -> dict:
    response = await client.post(
        API, json={"title": slug.title(), "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    page = response.json()
    if publish:
        await client.post(f"{API}/{page['id']}/publish", json={})
    return page


class TestSoftDelete:
    async def test_a_deleted_page_leaves_the_list(self, authed_client: AsyncClient) -> None:
        page = await _create(authed_client, "gone")

        await authed_client.delete(f"{API}/{page['id']}")

        listed = (await authed_client.get(API)).json()
        assert [p["slug"] for p in listed["items"]] == []

    async def test_a_deleted_page_is_a_404_by_id(self, authed_client: AsyncClient) -> None:
        """Not a row with a flag: every ordinary read must refuse it, or an
        editor could still open and publish something they deleted."""
        page = await _create(authed_client, "hidden")

        await authed_client.delete(f"{API}/{page['id']}")

        assert (await authed_client.get(f"{API}/{page['id']}")).status_code == 404

    async def test_a_published_page_goes_offline_at_once(
        self, authed_client: AsyncClient
    ) -> None:
        """The 30-day window is for recovery, not for staying live."""
        page = await _create(authed_client, "live-then-binned", publish=True)
        assert (await authed_client.get("/p/live-then-binned")).status_code == 200

        await authed_client.delete(f"{API}/{page['id']}")

        assert (await authed_client.get("/p/live-then-binned")).status_code == 404

    async def test_it_leaves_the_sitemap(self, authed_client: AsyncClient) -> None:
        page = await _create(authed_client, "mapped", publish=True)
        await authed_client.delete(f"{API}/{page['id']}")

        body = (await authed_client.get("/sitemap.xml")).text

        assert "mapped" not in body

    async def test_it_is_recoverable_rather_than_removed(
        self, authed_client: AsyncClient
    ) -> None:
        page = await _create(authed_client, "still-there")

        await authed_client.delete(f"{API}/{page['id']}")

        trashed = (await authed_client.get(f"{API}/trash")).json()
        assert [p["slug"] for p in trashed["items"]] == ["still-there"]


class TestTrashListing:
    async def test_it_shows_only_trashed_pages(self, authed_client: AsyncClient) -> None:
        kept = await _create(authed_client, "kept")
        binned = await _create(authed_client, "binned")
        await authed_client.delete(f"{API}/{binned['id']}")

        listed = (await authed_client.get(f"{API}/trash")).json()

        assert [p["slug"] for p in listed["items"]] == ["binned"]
        assert kept["slug"] not in [p["slug"] for p in listed["items"]]

    async def test_trash_route_is_not_read_as_a_page_id(
        self, authed_client: AsyncClient
    ) -> None:
        assert (await authed_client.get(f"{API}/trash")).status_code == 200


class TestRestore:
    async def test_it_comes_back_into_the_list(self, authed_client: AsyncClient) -> None:
        page = await _create(authed_client, "back")
        await authed_client.delete(f"{API}/{page['id']}")

        restored = await authed_client.post(f"{API}/{page['id']}/restore")

        assert restored.status_code == 200
        listed = (await authed_client.get(API)).json()
        assert [p["slug"] for p in listed["items"]] == ["back"]

    async def test_it_returns_as_a_draft_not_live(self, authed_client: AsyncClient) -> None:
        """Restore must not put a page back on the public site by itself."""
        page = await _create(authed_client, "was-live", publish=True)
        await authed_client.delete(f"{API}/{page['id']}")

        await authed_client.post(f"{API}/{page['id']}/restore")

        assert (await authed_client.get(f"{API}/{page['id']}")).json()["status"] == "draft"
        assert (await authed_client.get("/p/was-live")).status_code == 404

    async def test_the_slug_is_still_held_while_trashed(
        self, authed_client: AsyncClient
    ) -> None:
        """Releasing it would let a new page take the URL, and restoring the old
        one would then collide or silently steal the address back."""
        page = await _create(authed_client, "claimed")
        await authed_client.delete(f"{API}/{page['id']}")

        clash = await authed_client.post(
            API, json={"title": "Clash", "slug": "claimed", "draft_data": {"content": []}}
        )

        assert clash.status_code == 409


class TestPurge:
    async def test_it_leaves_the_trash_for_good(self, authed_client: AsyncClient) -> None:
        page = await _create(authed_client, "forever")
        await authed_client.delete(f"{API}/{page['id']}")

        await authed_client.delete(f"{API}/{page['id']}/purge")

        trashed = (await authed_client.get(f"{API}/trash")).json()
        assert trashed["items"] == []

    async def test_it_frees_the_slug(self, authed_client: AsyncClient) -> None:
        page = await _create(authed_client, "reusable")
        await authed_client.delete(f"{API}/{page['id']}")
        await authed_client.delete(f"{API}/{page['id']}/purge")

        again = await authed_client.post(
            API, json={"title": "Again", "slug": "reusable", "draft_data": {"content": []}}
        )

        assert again.status_code == 201


class TestRetentionSweep:
    async def test_it_removes_only_what_is_past_the_window(self, db) -> None:
        service = PagesService(db)
        old = Page(slug="old", title="Old", draft_data={}, deleted_at=datetime.now(UTC)
                   - timedelta(days=RETENTION_DAYS + 1))
        recent = Page(slug="recent", title="Recent", draft_data={}, deleted_at=datetime.now(UTC))
        live = Page(slug="live", title="Live", draft_data={})
        db.add_all([old, recent, live])
        await db.flush()

        removed = await service.purge_expired()

        assert removed == 1
        left = sorted((await db.execute(select(Page.slug))).scalars().all())
        assert left == ["live", "recent"]

    async def test_it_is_a_no_op_on_an_empty_trash(self, db) -> None:
        assert await PagesService(db).purge_expired() == 0
