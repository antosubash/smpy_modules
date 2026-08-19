"""Category faceting and listing cache headers.

Both exist because the listing has two very different audiences. Editors use it
to find the article they are looking for — which is usually the one nobody has
finished. Anonymous visitors reach it through the feed block on every public
page that carries one, which is what makes an uncacheable response expensive.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news.constants import (
    PRIVATE_CACHE_CONTROL,
    PUBLIC_CACHE_CONTROL,
    ROUTE_PREFIX_API,
    UNCATEGORISED,
)
from pagebuilder.models import PageStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CATEGORIES = f"{ROUTE_PREFIX_API}/categories"


async def _seed(client, rows: list[tuple[str, str, str]]) -> None:
    """rows of (slug, title, category)."""
    async with client.db_state.session_factory() as db:
        for slug, title, category in rows:
            page = await make_page(db, slug=slug, title=title)
            await service.create(db, page_id=page.id, category=category, published_at=None)
        await db.commit()


class TestUncategorised:
    """A blank category could not be filtered for at all.

    ``category=""`` arrives falsy and reads as "no category filter", so the one
    query an editor most wants — show me the articles nobody has filed — had no
    spelling on the wire. It needed a sentinel, not a fix to the empty case.
    """

    async def test_lists_only_the_articles_with_no_category(self, editor_client) -> None:
        await _seed(
            editor_client,
            [("a", "Filed", "Events"), ("b", "Unfiled", ""), ("c", "Also unfiled", "")],
        )

        body = (await editor_client.get(f"{ARTICLES}?category={UNCATEGORISED}")).json()

        assert sorted(item["title"] for item in body["items"]) == ["Also unfiled", "Unfiled"]
        assert body["total"] == 2

    async def test_an_empty_category_still_means_no_filter(self, editor_client) -> None:
        # The behaviour the sentinel exists to leave alone.
        await _seed(editor_client, [("a", "Filed", "Events"), ("b", "Unfiled", "")])

        body = (await editor_client.get(f"{ARTICLES}?category=")).json()

        assert body["total"] == 2

    async def test_a_named_category_is_unaffected(self, editor_client) -> None:
        await _seed(editor_client, [("a", "Filed", "Events"), ("b", "Unfiled", "")])

        body = (await editor_client.get(f"{ARTICLES}?category=Events")).json()

        assert [item["title"] for item in body["items"]] == ["Filed"]

    async def test_an_article_literally_categorised_as_the_sentinel_is_not_special(
        self, editor_client
    ) -> None:
        """The sentinel is a wire value, so a real category spelled the same
        way is shadowed by it. Worth knowing rather than worth preventing —
        ``__none__`` is not a category anybody types by accident."""
        await _seed(editor_client, [("a", "Unfiled", ""), ("b", "Odd", UNCATEGORISED)])

        body = (await editor_client.get(f"{ARTICLES}?category={UNCATEGORISED}")).json()

        assert [item["title"] for item in body["items"]] == ["Unfiled"]


class TestCategoryCounts:
    async def test_counts_the_uncategorised_separately_from_the_named(
        self, editor_client
    ) -> None:
        """Not an item with a blank name: as a list entry it would be
        indistinguishable from the "All" option in the filter row."""
        await _seed(
            editor_client,
            [("a", "One", "Events"), ("b", "Two", "Events"), ("c", "Three", "")],
        )

        body = (await editor_client.get(CATEGORIES)).json()

        assert body["items"] == [{"category": "Events", "count": 2}]
        assert body["uncategorised"] == 1

    async def test_is_zero_when_everything_is_filed(self, editor_client) -> None:
        await _seed(editor_client, [("a", "One", "Events")])

        assert (await editor_client.get(CATEGORIES)).json()["uncategorised"] == 0

    async def test_an_anonymous_visitor_does_not_see_draft_articles_counted(
        self, anon_client, editor_client
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            published = await make_page(db, slug="pub", title="Published")
            draft = await make_page(db, slug="draft", title="Draft", status=PageStatus.DRAFT)
            await service.create(db, page_id=published.id, category="", published_at=None)
            await service.create(db, page_id=draft.id, category="Events", published_at=None)
            await db.commit()

        seen_by_editor = (await editor_client.get(CATEGORIES)).json()
        assert seen_by_editor["items"] == [{"category": "Events", "count": 1}]
        assert seen_by_editor["uncategorised"] == 1

        # Same database, no session: the draft is not there to be counted.
        async with anon_client.db_state.session_factory() as db:
            page = await make_page(db, slug="anon-pub", title="Public")
            await service.create(db, page_id=page.id, category="Events", published_at=None)
            draft_page = await make_page(
                db, slug="anon-draft", title="Hidden", status=PageStatus.DRAFT
            )
            await service.create(db, page_id=draft_page.id, category="Secret", published_at=None)
            await db.commit()

        body = (await anon_client.get(CATEGORIES)).json()

        assert body["items"] == [{"category": "Events", "count": 1}]


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
        response = await editor_client.get(ARTICLES)

        assert response.headers["cache-control"] == PRIVATE_CACHE_CONTROL

    async def test_an_administrators_listing_is_never_stored_either(
        self, admin_client
    ) -> None:
        # An admin resolves to WILDCARD rather than to a literal `news.edit`.
        assert (await admin_client.get(ARTICLES)).headers[
            "cache-control"
        ] == PRIVATE_CACHE_CONTROL

    async def test_a_signed_in_reader_without_edit_gets_the_public_answer(
        self, viewer_client
    ) -> None:
        # No drafts in it, so nothing about it is specific to this person.
        assert (await viewer_client.get(ARTICLES)).headers[
            "cache-control"
        ] == PUBLIC_CACHE_CONTROL
