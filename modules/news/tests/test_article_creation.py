"""Creating an article — mostly, how its address gets derived.

This used to be ``POST /articles/with-page``: one request that created a
pagebuilder page *and* attached news metadata to it, which was itself a fix for
an earlier two-request browser version that stranded empty pages whenever the
second call failed.

Both of those are gone. An article is one row, so creating one is one insert and
"stranded" has no referent — the ``TestNothingIsStranded`` class that used to
guard it proved a property the schema now makes unstateable. What survives is
everything about turning a headline into a URL, which is unchanged and still the
part with the sharp edges.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import locales
from news.constants import ARTICLE_BODY_URL, MAX_SLUG_ATTEMPTS, ROUTE_PREFIX_API
from news.content._slugs import free_slug
from news.models import ArticleStatus, NewsArticle
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _count(client) -> int:
    async with client.db_state.session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(NewsArticle)) or 0)


class TestCreate:
    async def test_creates_the_article_in_one_request(self, editor_client) -> None:
        response = await editor_client.post(
            ARTICLES, json={"title": "Field campaign in Estonia"}
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Field campaign in Estonia"
        assert body["slug"] == "field-campaign-in-estonia"
        # A brand-new article is a draft; the author is about to write the body.
        assert body["status"] == ArticleStatus.DRAFT.value
        assert await _count(editor_client) == 1

    async def test_hands_back_where_to_edit_the_body(self, editor_client) -> None:
        """Served rather than assembled in the browser.

        The value changed with the split — it used to be a pagebuilder editor
        URL — but the reason it is served at all did not: the admin list holds
        no opinion about how anything routes its editor, including this module.
        """
        body = (await editor_client.post(ARTICLES, json={"title": "Estonia"})).json()

        assert body["edit_url"] == ARTICLE_BODY_URL.format(article_id=body["id"])

    async def test_the_derived_slug_is_readable_rather_than_stamped(
        self, editor_client
    ) -> None:
        """The two-call version put ``Date.now()`` in every slug so a retry
        could not collide, leaving each article at ``/p/my-title-1755561234567``
        for life. Nothing needs that now: the request is atomic."""
        body = (
            await editor_client.post(ARTICLES, json={"title": "Sensor rollout"})
        ).json()

        assert body["slug"] == "sensor-rollout"
        assert body["url"] == "/news/sensor-rollout"

    async def test_a_second_article_of_the_same_name_gets_the_next_free_slug(
        self, editor_client
    ) -> None:
        first = await editor_client.post(ARTICLES, json={"title": "Weekly notes"})
        second = await editor_client.post(ARTICLES, json={"title": "Weekly notes"})
        third = await editor_client.post(ARTICLES, json={"title": "Weekly notes"})

        assert first.json()["slug"] == "weekly-notes"
        assert second.json()["slug"] == "weekly-notes-2"
        assert third.json()["slug"] == "weekly-notes-3"

    async def test_a_title_with_no_slug_characters_still_gets_an_article(
        self, editor_client
    ) -> None:
        # ``???`` folds to nothing, and an empty slug fails the column's
        # pattern with a 422 the author has no way to act on.
        response = await editor_client.post(ARTICLES, json={"title": "???"})

        assert response.status_code == 201
        assert response.json()["slug"]

    async def test_a_trashed_articles_slug_stays_claimed(self, editor_client) -> None:
        """Releasing it would let a new article take the URL, and restoring the
        old one would then collide or silently steal the address back."""
        first = (await editor_client.post(ARTICLES, json={"title": "Recycled"})).json()
        await editor_client.post(f"{ARTICLES}/{first['id']}/trash")

        second = await editor_client.post(ARTICLES, json={"title": "Recycled"})

        assert second.json()["slug"] == "recycled-2"

    async def test_an_author_supplied_slug_is_used_verbatim(
        self, editor_client
    ) -> None:
        response = await editor_client.post(
            ARTICLES, json={"title": "Sensor rollout", "slug": "north-site"}
        )

        assert response.json()["slug"] == "north-site"

    async def test_a_slug_the_column_would_reject_is_a_422(self, editor_client) -> None:
        """Not a 500.

        The URL field is free text and pre-filled from the headline, so an
        author editing it into ``North Site`` is the ordinary case rather than
        a malformed request. Letting the ValidationError escape from inside the
        handler turned it into a server error naming nothing the author could
        act on. Stating the pattern on the DTO moves the check to the boundary,
        where FastAPI answers with the field name.
        """
        response = await editor_client.post(
            ARTICLES, json={"title": "Sensor rollout", "slug": "North Site"}
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "slug"]
        assert await _count(editor_client) == 0

    async def test_an_author_supplied_slug_that_collides_is_reported(
        self, editor_client
    ) -> None:
        """Not silently suffixed. The URL is a thing they typed and expect to
        get, so changing it under them is worse than saying it is taken."""
        await editor_client.post(ARTICLES, json={"title": "One", "slug": "taken"})

        response = await editor_client.post(
            ARTICLES, json={"title": "Two", "slug": "taken"}
        )

        assert response.status_code == 409

    async def test_the_category_and_date_are_set_in_the_same_request(
        self, editor_client
    ) -> None:
        body = (
            await editor_client.post(
                ARTICLES,
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
                ARTICLES,
                json={"title": "Estonia", "published_at": "2026-02-01T18:00:00-06:00"},
            )
        ).json()

        assert body["published_at"].startswith("2026-02-01")

    async def test_a_reader_without_edit_cannot_create_one(
        self, viewer_client
    ) -> None:
        response = await viewer_client.post(ARTICLES, json={"title": "Estonia"})

        assert response.status_code in (401, 403)
        assert await _count(viewer_client) == 0

    async def test_an_empty_title_is_refused_before_anything_is_written(
        self, editor_client
    ) -> None:
        response = await editor_client.post(ARTICLES, json={"title": ""})

        assert response.status_code == 422
        assert await _count(editor_client) == 0

    async def test_a_new_article_opens_on_an_empty_document(
        self, editor_client
    ) -> None:
        """The canvas has to have something to open.

        This was ``empty_puck_document`` in the pagebuilder seam, because the
        shape was that editor's to define. It is news' own now, and a null body
        would put the author in front of a canvas that cannot mount.
        """
        created = (await editor_client.post(ARTICLES, json={"title": "Blank"})).json()

        detail = await editor_client.get(f"{ARTICLES}/{created['id']}/detail")

        assert detail.status_code == 200, detail.text
        assert detail.json()["draft_data"]["content"] == []


class TestRunningOutOfAddresses:
    """``free_slug`` gives up early, where the tag/category rule does not.

    Both derive a slug and both suffix it, and they now share the candidate
    shape (``news.slugify.suffixed``) — but not the cap or the failure mode, and
    deliberately. An article slug is a URL a reader keeps, so news stops after
    ``MAX_SLUG_ATTEMPTS`` and asks the author to choose rather than minting
    ``crowded-24``; ``unique_slug`` tries 998 and raises, which is right for a
    slug nobody typed. These pin the article half so the two cannot converge by
    accident.
    """

    async def test_it_gives_up_after_the_capped_number_of_attempts(self, db) -> None:
        for slug in ["crowded"] + [
            f"crowded-{n}" for n in range(2, MAX_SLUG_ATTEMPTS + 2)
        ]:
            await make_article(db, slug=slug)

        assert await free_slug(db, "crowded", locales.default()) == ""

    async def test_the_last_attempt_is_still_offered(self, db) -> None:
        # One short of exhaustion: the final suffix has to be tried, not skipped.
        for slug in ["crowded"] + [
            f"crowded-{n}" for n in range(2, MAX_SLUG_ATTEMPTS + 1)
        ]:
            await make_article(db, slug=slug)

        assert (
            await free_slug(db, "crowded", locales.default())
            == f"crowded-{MAX_SLUG_ATTEMPTS + 1}"
        )

    async def test_an_exhausted_title_is_a_409_rather_than_a_guess(
        self, editor_client
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            for slug in ["taken-out"] + [
                f"taken-out-{n}" for n in range(2, MAX_SLUG_ATTEMPTS + 2)
            ]:
                await make_article(db, slug=slug)
            await db.commit()

        response = await editor_client.post(ARTICLES, json={"title": "Taken out"})

        assert response.status_code == 409, response.text
