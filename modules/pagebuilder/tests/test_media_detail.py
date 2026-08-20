"""Asset detail: describing an asset, and refusing to delete one in use.

Deleting an asset that a page still references does not fail loudly — the row
goes, the file goes, and the page starts serving a broken image nobody notices.
That is the case these exist for, so the assertions are about the *refusal* as
much as about the delete.
"""

from __future__ import annotations

import pytest
from conftest import PNG_BYTES
from httpx import AsyncClient
from pagebuilder import media_usage
from pagebuilder.models import MediaAsset, Page

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder"


async def _asset(db, filename: str = "canopy.jpg") -> MediaAsset:
    asset = MediaAsset(
        filename=filename,
        original_filename=filename,
        content_type="image/jpeg",
        size_bytes=1024,
        variants={},
    )
    db.add(asset)
    await db.flush()
    await db.refresh(asset)
    return asset


async def _page_using(db, url: str, *, title: str = "User", published: bool = False):
    blocks = {"content": [{"type": "Image", "props": {"src": url}}]}
    page = Page(
        slug=title.lower().replace(" ", "-"),
        title=title,
        draft_data=blocks,
        published_data=blocks if published else None,
    )
    db.add(page)
    await db.flush()
    return page


class TestUsageQuery:
    async def test_an_unused_asset_has_no_usages(self, db) -> None:
        found, total = await media_usage.find(db, "/media/pagebuilder/lonely.jpg")

        assert (found, total) == ([], 0)

    async def test_a_page_referencing_the_url_is_found(self, db) -> None:
        url = "/media/pagebuilder/used.jpg"
        await _page_using(db, url, title="Uses it")

        found, total = await media_usage.find(db, url)

        assert total == 1
        assert found[0].title == "Uses it"

    async def test_a_draft_only_reference_is_marked_as_such(self, db) -> None:
        """A reference only a draft carries is a weaker claim than a live one."""
        url = "/media/pagebuilder/draft.jpg"
        await _page_using(db, url, title="Draft user", published=False)

        found, _ = await media_usage.find(db, url)

        assert found[0].draft_only is True

    async def test_a_published_reference_is_not_draft_only(self, db) -> None:
        url = "/media/pagebuilder/live.jpg"
        await _page_using(db, url, title="Live user", published=True)

        found, _ = await media_usage.find(db, url)

        assert found[0].draft_only is False

    async def test_an_empty_url_matches_nothing(self, db) -> None:
        """A blank needle would LIKE-match every page in the site."""
        await _page_using(db, "/media/pagebuilder/anything.jpg")

        assert await media_usage.find(db, "") == ([], 0)

    async def test_a_trashed_page_does_not_hold_an_asset_hostage(self, db) -> None:
        """Blocking on a page nobody can see would be impossible to act on."""
        from pagebuilder.service import PagesService

        url = "/media/pagebuilder/binned.jpg"
        page = await _page_using(db, url, title="Binned user")
        await PagesService(db).delete(page.id)

        assert await media_usage.find(db, url) == ([], 0)


class TestDetailEndpoints:
    async def test_alt_text_caption_and_credit_round_trip(
        self, authed_client: AsyncClient
    ) -> None:
        created = await authed_client.post(
            f"{API}/uploads",
            files={"file": ("shot.png", PNG_BYTES, "image/png")},
        )
        assert created.status_code in (200, 201), created.text
        asset_id = created.json()["id"]

        updated = await authed_client.put(
            f"{API}/uploads/{asset_id}",
            json={
                "alt_text": "Aerial view of mixed canopy over plot 14",
                "credit": "J. Okonkwo / field team",
            },
        )

        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["asset"]["alt_text"] == "Aerial view of mixed canopy over plot 14"
        assert body["asset"]["credit"] == "J. Okonkwo / field team"
        # Untouched fields stay as they were rather than being blanked.
        assert body["asset"]["caption"] == ""

    async def test_detail_reports_no_usage_for_a_fresh_upload(
        self, authed_client: AsyncClient
    ) -> None:
        created = await authed_client.post(
            f"{API}/uploads",
            files={"file": ("fresh.png", PNG_BYTES, "image/png")},
        )
        asset_id = created.json()["id"]

        detail = await authed_client.get(f"{API}/uploads/{asset_id}")

        assert detail.status_code == 200
        assert detail.json()["used_in_total"] == 0

    async def test_an_unused_asset_deletes(self, authed_client: AsyncClient) -> None:
        created = await authed_client.post(
            f"{API}/uploads",
            files={"file": ("gone.png", PNG_BYTES, "image/png")},
        )
        asset_id = created.json()["id"]

        removed = await authed_client.delete(f"{API}/uploads/{asset_id}/checked")

        assert removed.status_code == 204
        assert (await authed_client.get(f"{API}/uploads/{asset_id}")).status_code == 404

    async def test_a_used_asset_refuses_and_names_the_pages(
        self, authed_client: AsyncClient
    ) -> None:
        created = await authed_client.post(
            f"{API}/uploads",
            files={"file": ("busy.png", PNG_BYTES, "image/png")},
        )
        asset = created.json()
        await authed_client.post(
            f"{API}/pages",
            json={
                "title": "Depends on it",
                "slug": "depends-on-it",
                "draft_data": {"content": [{"type": "Image", "props": {"src": asset["url"]}}]},
            },
        )

        refused = await authed_client.delete(f"{API}/uploads/{asset['id']}/checked")

        assert refused.status_code == 409
        # Actionable, not merely obstructive: it says where to go and undo it.
        assert "Depends on it" in refused.json()["detail"]
        assert "Detach it there first" in refused.json()["detail"]

    async def test_a_missing_asset_is_a_404(self, authed_client: AsyncClient) -> None:
        assert (await authed_client.get(f"{API}/uploads/999999")).status_code == 404
