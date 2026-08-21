"""A page whose public URL belongs to another module.

``public_claims`` is the one place pagebuilder admits that a page might be
presented by a neighbour — a news article, say — which wants its own address
for it. Two addresses for one document is a duplicate-content problem, so a
claim moves the address rather than adding one: the viewer stops answering and
the sitemap advertises the claimant's URL instead.

Everything here registers a fake claim rather than importing a real claimant.
That is the contract under test: pagebuilder must learn nothing about who
claimed a slug beyond the path it hands back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from httpx import AsyncClient
from pagebuilder import public_claims
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _no_leaked_claims():
    """Registration is process-global, so a claim left behind would change the
    answer of every later test in this process."""
    public_claims.reset()
    yield
    public_claims.reset()


def claiming(*slugs: str, prefix: str = "/elsewhere"):
    """A claim that owns exactly these slugs."""

    async def claim(session: AsyncSession, asked: Sequence[str]) -> Mapping[str, str]:
        return {slug: f"{prefix}/{slug}" for slug in asked if slug in slugs}

    return claim


async def _publish(client: AsyncClient, slug: str) -> int:
    create = await client.post(
        "/api/pagebuilder/pages",
        json={"title": slug, "slug": slug, "draft_data": {"content": []}},
    )
    assert create.status_code == 201, create.text
    page_id = create.json()["id"]
    assert (await client.post(f"/api/pagebuilder/pages/{page_id}/publish")).status_code == 200
    return page_id


class TestResolve:
    async def test_no_claims_owns_nothing(self, db: AsyncSession) -> None:
        assert await public_claims.resolve(db, ["a", "b"]) == {}

    async def test_returns_only_the_claimed(self, db: AsyncSession) -> None:
        public_claims.register(claiming("a"))

        assert await public_claims.resolve(db, ["a", "b"]) == {"a": "/elsewhere/a"}

    async def test_an_empty_ask_never_reaches_a_claim(self, db: AsyncSession) -> None:
        async def explodes(session, slugs):
            raise AssertionError("should not be called for an empty set")

        public_claims.register(explodes)

        assert await public_claims.resolve(db, []) == {}

    async def test_the_first_claim_wins_a_contested_slug(
        self, db: AsyncSession
    ) -> None:
        """Two modules claiming one page is a misconfiguration, not something
        to arbitrate here — but the winner has to be stable, or registration
        order decides silently and the sitemap disagrees with itself run to
        run."""
        public_claims.register(claiming("a", prefix="/first"))
        public_claims.register(claiming("a", prefix="/second"))

        assert await public_claims.resolve(db, ["a"]) == {"a": "/first/a"}

    async def test_claimed_url_is_none_when_unowned(self, db: AsyncSession) -> None:
        public_claims.register(claiming("a"))

        assert await public_claims.claimed_url(db, "b") is None


class TestViewer:
    async def test_a_claimed_page_is_not_served_here(
        self, authed_client: AsyncClient
    ) -> None:
        """404 rather than a redirect: the two addresses were never equivalent,
        so there is no old address to forward from."""
        await _publish(authed_client, "claimed-page")
        public_claims.register(claiming("claimed-page"))

        assert (await authed_client.get("/p/claimed-page")).status_code == 404

    async def test_an_unclaimed_page_still_serves(self, authed_client: AsyncClient) -> None:
        # The claim must move one page's address, not shut the viewer off.
        await _publish(authed_client, "ordinary-page")
        public_claims.register(claiming("something-else"))

        assert (await authed_client.get("/p/ordinary-page")).status_code == 200


class TestSitemap:
    async def test_advertises_the_claimants_address(
        self, authed_client: AsyncClient
    ) -> None:
        """Without this the sitemap sends a crawler to the exact URL the viewer
        now refuses — a 404 in a document whose only job is listing live URLs."""
        await _publish(authed_client, "claimed-page")
        await _publish(authed_client, "ordinary-page")
        public_claims.register(claiming("claimed-page"))

        body = (await authed_client.get("/sitemap.xml")).text

        assert "/elsewhere/claimed-page" in body
        assert "/p/claimed-page" not in body
        assert "/p/ordinary-page" in body

    async def test_an_old_address_does_not_forward_into_a_claim(
        self, authed_client: AsyncClient
    ) -> None:
        """A page renamed *into* something another module claims has no address
        here any more. Forwarding to one that would itself 404 wastes a
        crawler's hop to say exactly what a 404 already says."""
        page_id = await _publish(authed_client, "before")
        renamed = await authed_client.put(
            f"/api/pagebuilder/pages/{page_id}", json={"slug": "after"}
        )
        assert renamed.status_code == 200, renamed.text
        republished = await authed_client.post(f"/api/pagebuilder/pages/{page_id}/publish")
        assert republished.status_code == 200
        public_claims.register(claiming("after"))

        old = await authed_client.get("/p/before", follow_redirects=False)

        assert old.status_code == 404

    async def test_an_ordinary_rename_still_forwards(
        self, authed_client: AsyncClient
    ) -> None:
        # The claim must not break redirects for everyone else.
        page_id = await _publish(authed_client, "was-here")
        await authed_client.put(f"/api/pagebuilder/pages/{page_id}", json={"slug": "now-here"})
        republished = await authed_client.post(f"/api/pagebuilder/pages/{page_id}/publish")
        assert republished.status_code == 200

        old = await authed_client.get("/p/was-here", follow_redirects=False)

        assert old.status_code == 301
        assert old.headers["location"] == "/p/now-here"
