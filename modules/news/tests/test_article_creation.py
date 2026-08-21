"""Creating an article, and publishing the page behind it.

Both used to run in the browser against pagebuilder's own API. What that cost
is what these cover: a borrowed CSRF cookie, and — because the two writes were
in separate transactions — an empty articleless page stranded in pagebuilder
whenever the second one failed.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news.constants import ROUTE_PREFIX_API
from news.contracts.schemas import ArticleStatus
from news.integrations import pagebuilder as pb
from news.integrations.pagebuilder import Page
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

WITH_PAGE = f"{ROUTE_PREFIX_API}/articles/with-page"
ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _count(client, model) -> int:
    async with client.db_state.session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(model)) or 0)


class TestCreateWithPage:
    async def test_creates_the_page_and_the_article_in_one_request(
        self, editor_client
    ) -> None:
        response = await editor_client.post(
            WITH_PAGE, json={"title": "Field campaign in Estonia"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Field campaign in Estonia"
        assert body["slug"] == "field-campaign-in-estonia"
        # A brand-new page is a draft; the editor is about to write the body.
        assert body["page_status"] == ArticleStatus.DRAFT.value
        assert await _count(editor_client, Page) == 1

    async def test_hands_back_where_to_edit_the_body(self, editor_client) -> None:
        """Served rather than assembled in the browser, so the admin list holds
        no opinion about how pagebuilder routes its editor."""
        body = (await editor_client.post(WITH_PAGE, json={"title": "Estonia"})).json()

        assert body["edit_url"] == pb.page_editor_path(body["page_id"])

    async def test_the_derived_slug_is_readable_rather_than_stamped(
        self, editor_client
    ) -> None:
        """The two-call version put ``Date.now()`` in every slug so a retry
        could not collide, leaving each article at ``/p/my-title-1755561234567``
        for life. Nothing needs that now: the request is atomic."""
        body = (await editor_client.post(WITH_PAGE, json={"title": "Sensor rollout"})).json()

        assert body["slug"] == "sensor-rollout"
        assert body["url"] == "/news/sensor-rollout"

    async def test_a_second_article_of_the_same_name_gets_the_next_free_slug(
        self, editor_client
    ) -> None:
        first = await editor_client.post(WITH_PAGE, json={"title": "Weekly notes"})
        second = await editor_client.post(WITH_PAGE, json={"title": "Weekly notes"})
        third = await editor_client.post(WITH_PAGE, json={"title": "Weekly notes"})

        assert first.json()["slug"] == "weekly-notes"
        assert second.json()["slug"] == "weekly-notes-2"
        assert third.json()["slug"] == "weekly-notes-3"

    async def test_a_title_with_no_slug_characters_still_gets_a_page(
        self, editor_client
    ) -> None:
        # ``???`` folds to nothing, and an empty slug fails pagebuilder's
        # pattern with a 422 the author has no way to act on.
        response = await editor_client.post(WITH_PAGE, json={"title": "???"})

        assert response.status_code == 201
        assert response.json()["slug"]

    async def test_an_author_supplied_slug_is_used_verbatim(self, editor_client) -> None:
        response = await editor_client.post(
            WITH_PAGE, json={"title": "Sensor rollout", "slug": "north-site"}
        )

        assert response.json()["slug"] == "north-site"

    async def test_a_slug_the_page_column_would_reject_is_a_422(
        self, editor_client
    ) -> None:
        """Not a 500.

        The URL field is free text and pre-filled from the headline, so an
        author editing it into ``North Site`` is the ordinary case rather than
        a malformed request. Pagebuilder's own schema rejects that pattern, and
        letting the ValidationError escape from inside the handler turned it
        into a server error naming nothing the author could act on. Restating
        the pattern on this module's DTO moves the check to the boundary, where
        FastAPI answers with the field name.
        """
        response = await editor_client.post(
            WITH_PAGE, json={"title": "Sensor rollout", "slug": "North Site"}
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "slug"]
        assert await _count(editor_client, Page) == 0

    async def test_an_author_supplied_slug_that_collides_is_reported(
        self, editor_client
    ) -> None:
        """Not silently suffixed. The URL is a thing they typed and expect to
        get, so changing it under them is worse than saying it is taken."""
        await editor_client.post(WITH_PAGE, json={"title": "One", "slug": "taken"})

        response = await editor_client.post(
            WITH_PAGE, json={"title": "Two", "slug": "taken"}
        )

        assert response.status_code == 409

    async def test_the_category_and_date_are_set_in_the_same_request(
        self, editor_client
    ) -> None:
        body = (
            await editor_client.post(
                WITH_PAGE,
                json={
                    "title": "Estonia",
                    "category": "Field notes",
                    "published_at": "2026-02-01T00:00:00Z",
                },
            )
        ).json()

        assert body["category"] == "Field notes"
        assert body["published_at"].startswith("2026-02-01")

    async def test_the_date_is_the_calendar_day_the_author_picked(
        self, editor_client
    ) -> None:
        """6pm on the 1st in UTC-6 is the 2nd in UTC. Taking the offset into
        account would list an article on a day nobody chose."""
        body = (
            await editor_client.post(
                WITH_PAGE,
                json={"title": "Estonia", "published_at": "2026-02-01T18:00:00-06:00"},
            )
        ).json()

        assert body["published_at"].startswith("2026-02-01")

    async def test_a_reader_without_edit_cannot_create_one(self, viewer_client) -> None:
        response = await viewer_client.post(WITH_PAGE, json={"title": "Estonia"})

        assert response.status_code in (401, 403)
        assert await _count(viewer_client, Page) == 0

    async def test_an_empty_title_is_refused_before_anything_is_written(
        self, editor_client
    ) -> None:
        response = await editor_client.post(WITH_PAGE, json={"title": ""})

        assert response.status_code == 422
        assert await _count(editor_client, Page) == 0


class TestNothingIsStranded:
    """The reason this is one request rather than two.

    The browser used to create the page, then attach — and a failure of the
    second left an empty page nothing would ever clean up. The dialog kept the
    first request's page id purely so a retry could adopt it.
    """

    async def test_a_failed_create_leaves_no_page_behind(
        self, editor_client, monkeypatch
    ) -> None:
        async def _explodes(*args, **kwargs):
            raise RuntimeError("attach failed")

        monkeypatch.setattr(service, "create", _explodes)

        with pytest.raises(RuntimeError):
            await editor_client.post(WITH_PAGE, json={"title": "Estonia"})

        assert await _count(editor_client, Page) == 0


class TestPublish:
    async def test_publishes_the_page_behind_the_article(self, editor_client) -> None:
        created = (await editor_client.post(WITH_PAGE, json={"title": "Estonia"})).json()

        response = await editor_client.post(
            f"{ARTICLES}/{created['id']}/publish", json={}
        )

        assert response.status_code == 200
        assert response.json()["page_status"] == ArticleStatus.PUBLISHED.value

    async def test_a_missing_article_is_a_404(self, editor_client) -> None:
        assert (await editor_client.post(f"{ARTICLES}/999/publish", json={})).status_code == 404

    async def test_a_reader_without_edit_cannot_publish(
        self, viewer_client, editor_client
    ) -> None:
        async with viewer_client.db_state.session_factory() as db:
            page = await make_page(db, slug="draft-one", title="Draft")
            article = await service.create(
                db, page_id=page.id, category="", published_at=None
            )
            await db.commit()
            article_id = article.id

        response = await viewer_client.post(f"{ARTICLES}/{article_id}/publish", json={})

        assert response.status_code in (401, 403)


class TestAttachRace:
    """Attaching a page that lost a race is a 409, not a 500.

    ``attach`` checks whether the page is already an article before creating
    the row, but a check is not a lock: two requests for the same page both
    pass it and the loser meets the unique index on ``page_id`` instead. That
    is the same conflict the check reports, so it has to answer the same way.
    """

    async def test_the_loser_of_a_race_gets_the_same_409_as_the_check(
        self, editor_client, monkeypatch
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            page = await make_page(db, slug="contested", title="Contested")
            await service.create(db, page_id=page.id, category="", published_at=None)
            await db.commit()
            page_id = page.id

        # Stand in for the window between the check and the insert: the row is
        # there, but the request that is about to write does not see it.
        # Without this the pre-check catches everything and the handler's
        # IntegrityError branch is never reached — verified by removing that
        # branch and watching this test fail.
        async def _sees_nothing(*args, **kwargs):
            return None

        monkeypatch.setattr(service, "get_by_page", _sees_nothing)

        response = await editor_client.post(
            ARTICLES, json={"page_id": page_id, "category": "", "published_at": None}
        )

        assert response.status_code == 409
        assert str(page_id) in response.json()["detail"]
