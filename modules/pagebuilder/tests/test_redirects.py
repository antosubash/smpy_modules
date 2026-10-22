"""Slug renames leave a redirect behind.

The editor promises one, and a promise about URLs is only worth anything if the
old address actually resolves — so these drive the *public* route rather than
the redirect table. A row that exists but never redirects has not kept the
promise.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pagebuilder import redirects
from pagebuilder.models import Page, PageStatus

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _published(client: AsyncClient, slug: str) -> dict:
    created = await client.post(
        API, json={"title": slug.title(), "slug": slug, "draft_data": {"content": []}}
    )
    assert created.status_code == 201, created.text
    page = created.json()
    await client.post(f"{API}/{page['id']}/publish", json={})
    return page


class TestRename:
    async def test_the_old_address_redirects_to_the_new_one(
        self, authed_client: AsyncClient
    ) -> None:
        page = await _published(authed_client, "old-address")

        await authed_client.put(f"{API}/{page['id']}", json={"slug": "new-address"})
        await authed_client.post(f"{API}/{page['id']}/publish", json={})

        moved = await authed_client.get("/p/old-address")
        assert moved.status_code == 301
        assert moved.headers["location"] == "/p/new-address"

    async def test_a_rename_that_the_database_rejects_leaves_no_redirect(
        self, authed_client: AsyncClient
    ) -> None:
        """Otherwise a failed rename points an old URL at an address the page
        never took."""
        await _published(authed_client, "taken")
        page = await _published(authed_client, "mover")

        clash = await authed_client.put(f"{API}/{page['id']}", json={"slug": "taken"})
        assert clash.status_code == 409

        # `mover` still serves its own page rather than redirecting anywhere.
        assert (await authed_client.get("/p/mover")).status_code == 200

    async def test_renaming_twice_collapses_to_one_hop(
        self, authed_client: AsyncClient
    ) -> None:
        """Every old address points at the page, and the page knows where it
        lives now — so no chain of redirects can build up."""
        page = await _published(authed_client, "first")
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "second"})
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "third"})
        await authed_client.post(f"{API}/{page['id']}/publish", json={})

        for old in ("first", "second"):
            moved = await authed_client.get(f"/p/{old}")
            assert moved.status_code == 301, old
            assert moved.headers["location"] == "/p/third"

    async def test_reclaiming_an_old_slug_does_not_loop(
        self, authed_client: AsyncClient
    ) -> None:
        """Renaming back would otherwise leave `a -> a`, which redirects the
        page off itself forever."""
        page = await _published(authed_client, "there")
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "back"})
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "there"})
        await authed_client.post(f"{API}/{page['id']}/publish", json={})

        assert (await authed_client.get("/p/there")).status_code == 200

    async def test_an_unrelated_missing_slug_is_still_a_404(
        self, authed_client: AsyncClient
    ) -> None:
        assert (await authed_client.get("/p/never-existed")).status_code == 404

    async def test_a_trashed_page_does_not_redirect(
        self, authed_client: AsyncClient
    ) -> None:
        """A trashed page is offline; sending its old address to it would put
        the visitor on a 404 by a slower route."""
        page = await _published(authed_client, "binned-old")
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "binned-new"})
        await authed_client.delete(f"{API}/{page['id']}")

        assert (await authed_client.get("/p/binned-old")).status_code == 404


class TestRedirectTargetMustBeLive:
    """An old address forwards only to a page the public viewer would serve.

    The redirect is a 301, which browsers cache: one that once sent a visitor
    to a 404 keeps doing so after the page comes back (#109).
    """

    async def test_an_unpublished_target_does_not_redirect(
        self, authed_client: AsyncClient
    ) -> None:
        page = await _published(authed_client, "draft-old")
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "draft-new"})
        await authed_client.post(f"{API}/{page['id']}/publish", json={})
        await authed_client.post(f"{API}/{page['id']}/unpublish", json={})

        # Unpublish keeps the snapshot, so status alone has to stop the hop.
        assert (await authed_client.get("/p/draft-new")).status_code == 404
        assert (await authed_client.get("/p/draft-old")).status_code == 404

    async def test_republishing_brings_the_redirect_back(
        self, authed_client: AsyncClient
    ) -> None:
        page = await _published(authed_client, "back-old")
        await authed_client.put(f"{API}/{page['id']}", json={"slug": "back-new"})
        await authed_client.post(f"{API}/{page['id']}/unpublish", json={})
        await authed_client.post(f"{API}/{page['id']}/publish", json={})

        moved = await authed_client.get("/p/back-old")
        assert moved.status_code == 301
        assert moved.headers["location"] == "/p/back-new"

    async def test_a_published_page_without_a_snapshot_does_not_redirect(
        self, db
    ) -> None:
        """The viewer 404s a published row with nothing to render, so its old
        address must not forward to it either. Not reachable through the API,
        hence built directly — and why the snapshot is checked in Python: a
        ``None`` in a JSON column is stored as JSON ``null``, not SQL NULL."""
        page = Page(
            slug="hollow-new",
            title="Hollow",
            draft_data={"content": []},
            published_data=None,
            status=PageStatus.PUBLISHED,
        )
        db.add(page)
        await db.flush()
        assert page.id is not None
        await redirects.record(
            db,
            page_id=page.id,
            old_slug="hollow-old",
            new_slug="hollow-new",
            locale=page.locale,
        )

        assert await redirects.resolve(db, "hollow-old", page.locale) is None

        page.published_data = {"content": []}
        await db.flush()
        assert await redirects.resolve(db, "hollow-old", page.locale) == "hollow-new"
