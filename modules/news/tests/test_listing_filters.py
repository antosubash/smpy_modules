"""Cache headers on the two anonymously-readable listings.

They exist because the listing has two very different audiences. Editors use it
to find the article they are looking for, which is usually the one nobody has
finished, so their answer includes drafts. Anonymous visitors reach it through
the feed block on every public page that carries one — which is what makes an
uncacheable response expensive, and a wrongly-cacheable one a leak.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.constants import (
    PRIVATE_CACHE_CONTROL,
    PUBLIC_CACHE_CONTROL,
    ROUTE_PREFIX_API,
)

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CATEGORIES = f"{ROUTE_PREFIX_API}/categories"


async def _seed(client, rows: list[tuple[str, str, str]]) -> None:
    """rows of (slug, title, category)."""
    async with client.db_state.session_factory() as db:
        for slug, title, category in rows:
            await make_article(db, slug=slug, title=title, category=category)
        await db.commit()


class TestCacheHeaders:
    """The feed block runs on every public page carrying it.

    Without a cacheable response that is a database round trip per page view;
    with the wrong one it is an editor's draft list served to a stranger.
    """

    async def test_the_anonymous_listing_may_be_held_by_a_shared_cache(
        self, anon_client
    ) -> None:
        response = await anon_client.get(ARTICLES)

        assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
        assert response.headers["cache-control"].startswith("public")

    async def test_the_anonymous_category_list_too(self, anon_client) -> None:
        assert (await anon_client.get(CATEGORIES)).headers[
            "cache-control"
        ] == PUBLIC_CACHE_CONTROL

    async def test_an_editors_listing_is_never_stored(self, editor_client) -> None:
        # It includes drafts, so it differs by permission and must not be
        # served to the next visitor out of a shared cache.
        await _seed(editor_client, [("a", "Filed", "Events")])

        response = await editor_client.get(ARTICLES)

        assert response.headers["cache-control"] == PRIVATE_CACHE_CONTROL

    async def test_an_administrators_listing_is_never_stored_either(
        self, admin_client
    ) -> None:
        # An admin resolves to WILDCARD rather than to a literal `news.edit`,
        # which a naive membership test would miss.
        assert (await admin_client.get(ARTICLES)).headers[
            "cache-control"
        ] == PRIVATE_CACHE_CONTROL

    async def test_the_editors_category_list_is_never_stored_either(
        self, editor_client
    ) -> None:
        assert (await editor_client.get(CATEGORIES)).headers[
            "cache-control"
        ] == PRIVATE_CACHE_CONTROL

    async def test_a_signed_in_reader_without_edit_gets_the_public_answer(
        self, viewer_client
    ) -> None:
        # No drafts in it, so nothing about it is specific to this person and
        # a shared cache may serve it to the next visitor.
        assert (await viewer_client.get(ARTICLES)).headers[
            "cache-control"
        ] == PUBLIC_CACHE_CONTROL
