"""HTTP contract for the news API.

The e2e suite drives this through a browser, but always against published
articles and never past the first page of results — which is exactly why the
404-on-create and the never-visible-draft bugs survived it. These tests go at
the endpoints directly.

``TestAttach`` is now ``TestCreate``, and the difference is the point of the
split: creating an article used to mean POSTing a ``page_id`` that had to exist
already, and half its cases were about what happens when that page is missing,
gone, or already spoken for. One table means one insert, so those cases have no
subject any more.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from factories import make_article
from news import service
from news.constants import MAX_LIMIT, ROUTE_PREFIX_API
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CATEGORIES = f"{ROUTE_PREFIX_API}/categories"
DATED = datetime(2026, 2, 1, tzinfo=UTC)


async def _seed(client, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_article(db, **kwargs)


class TestCreate:
    async def test_returns_the_article_it_created(self, editor_client) -> None:
        response = await editor_client.post(
            ARTICLES, json={"title": "Attach me", "category": "News"}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "Attach me"
        assert body["slug"] == "attach-me"
        assert body["url"] == "/news/attach-me"
        # A new article is a draft. It used to inherit whatever status the page
        # it was attached to happened to be in, which meant creating an article
        # against an already-published page published it immediately.
        assert body["status"] == ArticleStatus.DRAFT.value

    async def test_derives_a_free_slug_when_the_title_collides(
        self, editor_client
    ) -> None:
        await editor_client.post(ARTICLES, json={"title": "Same title"})

        response = await editor_client.post(ARTICLES, json={"title": "Same title"})

        assert response.status_code == 201, response.text
        assert response.json()["slug"] == "same-title-2"

    async def test_an_author_supplied_slug_that_collides_is_a_409(
        self, editor_client
    ) -> None:
        """Reported rather than silently altered: the URL is a thing they typed."""
        await editor_client.post(ARTICLES, json={"title": "First", "slug": "mine"})

        response = await editor_client.post(
            ARTICLES, json={"title": "Second", "slug": "mine"}
        )

        assert response.status_code == 409

    async def test_rejects_a_malformed_slug_at_the_dto(self, editor_client) -> None:
        # A 422 naming the field, rather than the 500 a ValidationError raised
        # from inside the handler produces.
        response = await editor_client.post(
            ARTICLES, json={"title": "Spaces", "slug": "not a slug"}
        )
        assert response.status_code == 422

    async def test_succeeds_behind_a_full_page_of_dated_articles(
        self, editor_client
    ) -> None:
        """Regression: this returned 404 for a row it had just written.

        The new article is undated and the listing sorts undated last, so the
        old read-back — list the first MAX_LIMIT and scan — could not see it.
        """
        async with editor_client.db_state.session_factory() as db:
            for i in range(MAX_LIMIT):
                await make_article(
                    db,
                    slug=f"dated-{i}",
                    title=f"Dated {i}",
                    category="Archive",
                    published_at=DATED,
                )

        response = await editor_client.post(ARTICLES, json={"title": "Fresh"})

        assert response.status_code == 201, response.text
        assert response.json()["title"] == "Fresh"

    async def test_leaves_no_row_behind_when_it_fails(self, editor_client) -> None:
        """A rejected create must not be durable.

        The service used to commit, so a handler that raised afterwards left the
        row committed anyway. Nothing should have been written for a request
        that returned an error.
        """
        await editor_client.post(ARTICLES, json={"title": "First", "slug": "taken"})
        await editor_client.post(ARTICLES, json={"title": "Second", "slug": "taken"})

        listing = await editor_client.get(f"{ARTICLES}?limit={MAX_LIMIT}")
        assert listing.json()["total"] == 1


class TestPartialUpdate:
    async def test_updating_only_the_category_keeps_the_date(
        self, editor_client
    ) -> None:
        """Regression: any partial PUT silently cleared the publication date."""
        article = await _seed(
            editor_client, slug="keep-date", category="Before", published_at=DATED
        )

        response = await editor_client.put(
            f"{ARTICLES}/{article.id}", json={"category": "After"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["category"] == "After"
        assert body["published_at"] is not None, "an omitted field must not clear it"

    async def test_explicit_null_undates_the_article(self, editor_client) -> None:
        article = await _seed(
            editor_client, slug="undate", category="News", published_at=DATED
        )

        response = await editor_client.put(
            f"{ARTICLES}/{article.id}", json={"published_at": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["published_at"] is None

    async def test_renaming_the_slug_keeps_the_old_address_working(
        self, editor_client
    ) -> None:
        """A rename is not a private edit — the old URL is already in the wild.

        News used to get this from pagebuilder's redirect table, because the
        slug being renamed was a page's. It keeps its own now, and this is the
        assertion that the behaviour survived the move.
        """
        article = await _seed(editor_client, slug="old-name")

        response = await editor_client.put(
            f"{ARTICLES}/{article.id}", json={"slug": "new-name"}
        )

        assert response.status_code == 200, response.text
        assert response.json()["slug"] == "new-name"

        async with editor_client.db_state.session_factory() as db:
            from news import redirects

            assert await redirects.resolve(db, "old-name") == "new-name"

    async def test_missing_article_is_a_404(self, editor_client) -> None:
        response = await editor_client.put(f"{ARTICLES}/9999", json={"category": "x"})
        assert response.status_code == 404


class TestListing:
    async def _three(self, client) -> None:
        async with client.db_state.session_factory() as db:
            await make_article(
                db, slug="old", title="Old",
                published_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
            await make_article(db, slug="new", title="New", published_at=DATED)
            await make_article(db, slug="undated", title="Undated")

    async def test_orders_newest_first_with_undated_last(self, editor_client) -> None:
        await self._three(editor_client)

        titles = [
            item["title"] for item in (await editor_client.get(ARTICLES)).json()["items"]
        ]

        assert titles == ["New", "Old", "Undated"]

    async def test_undated_first_puts_work_in_progress_up_front(
        self, editor_client
    ) -> None:
        # The admin list's ordering: an undated article is work in progress,
        # and with pagination the default would bury it on the last page.
        await self._three(editor_client)

        body = (await editor_client.get(f"{ARTICLES}?undated_first=true")).json()

        assert [item["title"] for item in body["items"]] == ["Undated", "New", "Old"]

    async def test_filters_by_category(self, editor_client) -> None:
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="wanted", title="Wanted", category="Events")
            await make_article(db, slug="other", title="Other", category="Releases")

        body = (await editor_client.get(f"{ARTICLES}?category=Events")).json()

        assert [item["title"] for item in body["items"]] == ["Wanted"]
        assert body["total"] == 1

    async def test_delete_removes_the_article_outright(self, editor_client) -> None:
        """It used to be "detach", which left the page and its body standing.

        There is no second document any more, so the word had nothing left to
        mean and the route deletes.
        """
        article = await _seed(editor_client, slug="delete-me")

        response = await editor_client.delete(f"{ARTICLES}/{article.id}")

        assert response.status_code == 204
        assert (await editor_client.get(ARTICLES)).json()["total"] == 0
        async with editor_client.db_state.session_factory() as db:
            assert await service.get(db, article.id) is None
