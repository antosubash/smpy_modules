"""HTTP contract for the news API.

The e2e suite drives this through a browser, but always against published
pages and never past the first page of results — which is exactly why the
404-on-create and the never-visible-draft bugs survived it. These tests go at
the endpoints directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_page
from news import service
from news.constants import MAX_LIMIT, ROUTE_PREFIX_API
from pagebuilder.models import PageStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
CATEGORIES = f"{ROUTE_PREFIX_API}/categories"
DATED = datetime(2026, 2, 1, tzinfo=UTC)


async def _seed_page(client, **kwargs):
    async with client.db_state.session_factory() as db:
        return await make_page(db, **kwargs)


async def _seed_article(client, *, page_id, category="", published_at=None):
    async with client.db_state.session_factory() as db:
        article = await service.create(
            db, page_id=page_id, category=category, published_at=published_at
        )
        await db.commit()
        return article.id


class TestAttach:
    async def test_returns_the_article_it_created(self, editor_client) -> None:
        page = await _seed_page(editor_client, slug="attach-me", title="Attach me")

        response = await editor_client.post(
            ARTICLES, json={"page_id": page.id, "category": "News"}
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["page_id"] == page.id
        assert body["title"] == "Attach me"
        assert body["url"] == "/news/attach-me"

    async def test_read_back_serializes_page_status(self, editor_client) -> None:
        """Regression (#20): the attach read-back must not lazy-load
        ``Page.status``.

        The listing's ``load_only`` (issue #12) omitted ``status`` while
        ``_to_read`` serializes ``page_status`` (issue #17). The page is created
        on another session, so ``get_read_by_page`` loads it fresh, and reading
        the un-loaded ``status`` raised ``MissingGreenlet`` under the async
        session — a 500 for a row it had just written.
        """
        page = await _seed_page(editor_client, slug="status-me", title="Status me")

        response = await editor_client.post(
            ARTICLES, json={"page_id": page.id, "category": "News"}
        )

        assert response.status_code == 201, response.text
        assert response.json()["page_status"] == PageStatus.PUBLISHED.value

    async def test_succeeds_behind_a_full_page_of_dated_articles(
        self, editor_client
    ) -> None:
        """Regression: this returned 404 for a row it had just written.

        The new article is undated and the listing sorts undated last, so the
        old read-back — list the first MAX_LIMIT and scan — could not see it.
        """
        async with editor_client.db_state.session_factory() as db:
            for i in range(MAX_LIMIT):
                page = await make_page(db, slug=f"dated-{i}", title=f"Dated {i}")
                await service.create(
                    db, page_id=page.id, category="Archive", published_at=DATED
                )
            await db.commit()

        fresh = await _seed_page(editor_client, slug="fresh", title="Fresh")
        response = await editor_client.post(
            ARTICLES, json={"page_id": fresh.id, "category": "News"}
        )

        assert response.status_code == 201, response.text
        assert response.json()["title"] == "Fresh"

    async def test_rejects_a_page_that_does_not_exist(self, editor_client) -> None:
        response = await editor_client.post(ARTICLES, json={"page_id": 9999})
        assert response.status_code == 404

    async def test_rejects_a_page_that_is_already_an_article(
        self, editor_client
    ) -> None:
        page = await _seed_page(editor_client, slug="twice")
        await _seed_article(editor_client, page_id=page.id)

        response = await editor_client.post(ARTICLES, json={"page_id": page.id})

        assert response.status_code == 409

    async def test_leaves_no_row_behind_when_it_fails(self, editor_client) -> None:
        """A rejected attach must not be durable.

        The service used to commit, so a handler that raised afterwards left the
        row committed anyway. Nothing should have been written for a request
        that returned an error.
        """
        await editor_client.post(ARTICLES, json={"page_id": 9999})

        listing = await editor_client.get(f"{ARTICLES}?limit={MAX_LIMIT}")
        assert listing.json()["total"] == 0


class TestPartialUpdate:
    async def test_updating_only_the_category_keeps_the_date(
        self, editor_client
    ) -> None:
        """Regression: any partial PUT silently cleared the publication date."""
        page = await _seed_page(editor_client, slug="keep-date")
        article_id = await _seed_article(
            editor_client, page_id=page.id, category="Before", published_at=DATED
        )

        response = await editor_client.put(
            f"{ARTICLES}/{article_id}", json={"category": "After"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["category"] == "After"
        assert body["published_at"] is not None, "an omitted field must not clear it"

    async def test_explicit_null_undates_the_article(self, editor_client) -> None:
        page = await _seed_page(editor_client, slug="undate")
        article_id = await _seed_article(
            editor_client, page_id=page.id, category="News", published_at=DATED
        )

        response = await editor_client.put(
            f"{ARTICLES}/{article_id}", json={"published_at": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["published_at"] is None

    async def test_missing_article_is_a_404(self, editor_client) -> None:
        response = await editor_client.put(f"{ARTICLES}/9999", json={"category": "x"})
        assert response.status_code == 404


class TestDraftVisibility:
    """Regression: `_may_see_drafts` read `user.permissions`, which UserContext
    does not have, so it was always False and no editor ever saw a draft."""

    async def _draft_article(self, client) -> None:
        page = await _seed_page(
            client, slug="wip", title="Work in progress", status=PageStatus.DRAFT
        )
        await _seed_article(client, page_id=page.id, category="News")

    async def test_an_editor_sees_a_draft(self, editor_client) -> None:
        await self._draft_article(editor_client)

        body = (await editor_client.get(ARTICLES)).json()

        assert body["total"] == 1
        assert body["items"][0]["title"] == "Work in progress"
        # And the listing says *that* it is a draft — the admin list badges
        # rows with this rather than making a second request per page.
        assert body["items"][0]["page_status"] == "draft"

    async def test_an_admin_sees_a_draft(self, admin_client) -> None:
        # An admin resolves to WILDCARD rather than to a literal `news.edit`,
        # so a plain membership test against the resolved set would miss them.
        await self._draft_article(admin_client)

        assert (await admin_client.get(ARTICLES)).json()["total"] == 1

    async def test_an_anonymous_visitor_does_not(self, anon_client) -> None:
        # The whole point of the published/draft split: the public feed block
        # runs with no session and must show the published site only.
        await self._draft_article(anon_client)

        assert (await anon_client.get(ARTICLES)).json()["total"] == 0

    async def test_a_viewer_without_edit_does_not(self, viewer_client) -> None:
        await self._draft_article(viewer_client)

        assert (await viewer_client.get(ARTICLES)).json()["total"] == 0

    async def test_a_published_article_is_visible_to_everyone(
        self, anon_client
    ) -> None:
        page = await _seed_page(anon_client, slug="live", title="Live")
        await _seed_article(anon_client, page_id=page.id, category="News")

        body = (await anon_client.get(ARTICLES)).json()
        assert body["total"] == 1
        assert body["items"][0]["page_status"] == "published"

    async def test_categories_follow_the_same_rule(self, anon_client) -> None:
        await self._draft_article(anon_client)

        assert (await anon_client.get(CATEGORIES)).json()["items"] == []


class TestWritesRequirePermission:
    async def test_anonymous_cannot_attach(self, anon_client) -> None:
        response = await anon_client.post(ARTICLES, json={"page_id": 1})
        assert response.status_code == 401

    async def test_a_viewer_cannot_attach(self, viewer_client) -> None:
        response = await viewer_client.post(ARTICLES, json={"page_id": 1})
        assert response.status_code == 403

    async def test_a_viewer_cannot_detach(self, viewer_client) -> None:
        response = await viewer_client.delete(f"{ARTICLES}/1")
        assert response.status_code == 403


class TestListing:
    async def test_orders_newest_first_with_undated_last(self, editor_client) -> None:
        async with editor_client.db_state.session_factory() as db:
            old = await make_page(db, slug="old", title="Old")
            new = await make_page(db, slug="new", title="New")
            undated = await make_page(db, slug="undated", title="Undated")
            await service.create(
                db, page_id=old.id, category="", published_at=datetime(2025, 1, 1, tzinfo=UTC)
            )
            await service.create(db, page_id=new.id, category="", published_at=DATED)
            await service.create(db, page_id=undated.id, category="", published_at=None)
            await db.commit()

        titles = [item["title"] for item in (await editor_client.get(ARTICLES)).json()["items"]]

        assert titles == ["New", "Old", "Undated"]

    async def test_undated_first_puts_work_in_progress_up_front(
        self, editor_client
    ) -> None:
        # The admin list's ordering: an undated article is work in progress,
        # and with pagination the default would bury it on the last page.
        async with editor_client.db_state.session_factory() as db:
            old = await make_page(db, slug="old", title="Old")
            new = await make_page(db, slug="new", title="New")
            undated = await make_page(db, slug="undated", title="Undated")
            await service.create(
                db, page_id=old.id, category="", published_at=datetime(2025, 1, 1, tzinfo=UTC)
            )
            await service.create(db, page_id=new.id, category="", published_at=DATED)
            await service.create(db, page_id=undated.id, category="", published_at=None)
            await db.commit()

        body = (await editor_client.get(f"{ARTICLES}?undated_first=true")).json()

        assert [item["title"] for item in body["items"]] == ["Undated", "New", "Old"]

    async def test_filters_by_category(self, editor_client) -> None:
        async with editor_client.db_state.session_factory() as db:
            wanted = await make_page(db, slug="wanted", title="Wanted")
            other = await make_page(db, slug="other", title="Other")
            await service.create(db, page_id=wanted.id, category="Events", published_at=None)
            await service.create(db, page_id=other.id, category="Releases", published_at=None)
            await db.commit()

        body = (await editor_client.get(f"{ARTICLES}?category=Events")).json()

        assert [item["title"] for item in body["items"]] == ["Wanted"]
        assert body["total"] == 1

    async def test_detach_leaves_the_page_alone(self, editor_client) -> None:
        page = await _seed_page(editor_client, slug="detach-me")
        article_id = await _seed_article(editor_client, page_id=page.id)

        response = await editor_client.delete(f"{ARTICLES}/{article_id}")

        assert response.status_code == 204
        assert (await editor_client.get(ARTICLES)).json()["total"] == 0
        async with editor_client.db_state.session_factory() as db:
            assert await service.page_exists(db, page.id) is True
