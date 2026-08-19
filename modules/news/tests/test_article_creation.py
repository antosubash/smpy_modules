"""Creating articles — both the attach endpoint and the "New article" flow.

It used to be two calls made by the browser — create a page through
pagebuilder's API, then attach the article here — and both of the things that
went wrong with it came from that split: the first call was protected by
*another module's* CSRF cookie, and the two calls committed separately, so a
failure of the second stranded an empty articleless page. Neither is reachable
from a single endpoint sharing one transaction, and these tests pin the
behaviour that replaced them.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news.constants import ROUTE_PREFIX_API
from news.integrations import pagebuilder as pb
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"
WITH_PAGE = f"{ARTICLES}/with-page"


class TestCreatesBoth:
    async def test_creates_the_page_and_attaches_the_article(self, editor_client) -> None:
        response = await editor_client.post(WITH_PAGE, json={"title": "Field campaign"})

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["title"] == "Field campaign"
        assert body["page_status"] == "draft"
        assert body["published_at"] is None
        # The listing finds it, which is only true if both rows exist and the
        # join between them resolves.
        listed = (await editor_client.get(f"{ROUTE_PREFIX_API}/articles")).json()
        assert [item["id"] for item in listed["items"]] == [body["id"]]

    async def test_the_slug_is_readable_rather_than_timestamped(self, editor_client) -> None:
        """The whole point of moving this server-side.

        The browser version appended ``Date.now()`` to every slug to dodge
        collisions, so every article served at ``/p/my-title-1755561234567``
        for the rest of its life and the only fix was hand-editing the slug in
        the page editor.
        """
        response = await editor_client.post(WITH_PAGE, json={"title": "Field Campaign in Estonia"})

        assert response.json()["url"] == "/p/field-campaign-in-estonia"

    async def test_serves_the_editor_url_rather_than_the_client_building_one(
        self, editor_client
    ) -> None:
        body = (await editor_client.post(WITH_PAGE, json={"title": "Anything"})).json()

        assert body["edit_url"] == f"/pagebuilder/{body['page_id']}/edit"

    async def test_carries_category_and_date_when_given(self, editor_client) -> None:
        body = (
            await editor_client.post(
                WITH_PAGE,
                json={
                    "title": "Dated",
                    "category": "Events",
                    "published_at": "2026-02-01T00:00:00Z",
                },
            )
        ).json()

        assert body["category"] == "Events"
        assert body["published_at"].startswith("2026-02-01T00:00:00")


class TestSlugCollisions:
    async def test_a_repeated_title_takes_the_next_free_suffix(self, editor_client) -> None:
        first = await editor_client.post(WITH_PAGE, json={"title": "Annual report"})
        second = await editor_client.post(WITH_PAGE, json={"title": "Annual report"})
        third = await editor_client.post(WITH_PAGE, json={"title": "Annual report"})

        assert first.json()["url"] == "/p/annual-report"
        assert second.json()["url"] == "/p/annual-report-2"
        assert third.json()["url"] == "/p/annual-report-3"

    async def test_steps_around_a_page_it_did_not_create(self, editor_client) -> None:
        # A slug can be taken by a page written in pagebuilder directly. The
        # candidate scan is over every page, not only over news' own.
        await _seed_foreign_page(editor_client, slug="shared-name")

        body = (await editor_client.post(WITH_PAGE, json={"title": "Shared name"})).json()

        assert body["url"] == "/p/shared-name-2"

    async def test_a_title_with_no_slug_characters_still_creates(self, editor_client) -> None:
        """``slugify`` can legitimately return nothing.

        Pagebuilder's slug pattern is ``^[a-z0-9][a-z0-9-]*$``, so an empty or
        punctuation-led slug is a 422 rather than a cosmetic problem — and a
        title of "???" or one written in a non-Latin script produces exactly
        that.
        """
        response = await editor_client.post(WITH_PAGE, json={"title": "???"})

        assert response.status_code == 201, response.text
        slug = response.json()["slug"]
        assert slug and slug[0].isalnum()


class TestNothingIsStrandedOrLeaked:
    async def test_a_rejected_title_creates_no_page(self, editor_client) -> None:
        """The failure the two-call version could not clean up after.

        A title the schema rejects fails before either write, and a title that
        got past validation but failed to attach would roll the page back with
        it — either way pagebuilder is left with nothing.
        """
        response = await editor_client.post(WITH_PAGE, json={"title": ""})

        assert response.status_code == 422
        assert await _page_count(editor_client) == 0

    async def test_requires_permission(self, viewer_client) -> None:
        response = await viewer_client.post(WITH_PAGE, json={"title": "Not allowed"})

        assert response.status_code == 403
        assert await _page_count(viewer_client) == 0


async def _page_count(client) -> int:
    async with client.db_state.session_factory() as db:
        return int(await db.scalar(select(func.count()).select_from(pb.Page)) or 0)


async def _seed_foreign_page(client, *, slug: str):
    async with client.db_state.session_factory() as db:
        return await make_page(db, slug=slug, title="Written in pagebuilder")


class TestDisplayDateNormalisation:
    """``published_at`` is a date, and the API accepts an instant."""

    async def test_an_offset_east_of_utc_keeps_the_day_the_author_meant(
        self, editor_client
    ) -> None:
        body = (
            await editor_client.post(
                WITH_PAGE,
                json={"title": "East", "published_at": "2026-02-01T23:00:00+05:00"},
            )
        ).json()

        assert body["published_at"].startswith("2026-02-01T00:00:00")

    async def test_an_offset_west_of_utc_does_not_roll_the_day_forward(
        self, editor_client
    ) -> None:
        # 2026-02-01T23:00:00-06:00 is 2026-02-02T05:00Z. Stored verbatim it
        # would list under the 2nd, which is not the day that was sent.
        body = (
            await editor_client.post(
                WITH_PAGE,
                json={"title": "West", "published_at": "2026-02-01T23:00:00-06:00"},
            )
        ).json()

        assert body["published_at"].startswith("2026-02-01T00:00:00")

    async def test_an_update_normalises_too(self, editor_client) -> None:
        created = (await editor_client.post(WITH_PAGE, json={"title": "Later"})).json()

        updated = await editor_client.put(
            f"{ROUTE_PREFIX_API}/articles/{created['id']}",
            json={"published_at": "2026-03-05T13:45:12.5Z"},
        )

        assert updated.json()["published_at"].startswith("2026-03-05T00:00:00")


class TestAttachRace:
    async def test_a_concurrent_duplicate_is_a_conflict_not_a_server_error(
        self, editor_client, monkeypatch
    ) -> None:
        """The check-then-create above is not a lock.

        Two requests attaching the same page both pass the "already an article"
        check, and the loser meets the unique index on ``page_id`` instead. It
        is the same conflict the check reports, so it gets the same status —
        unhandled, the IntegrityError surfaced as a 500.

        The lookup is stubbed rather than genuinely raced: the window is a few
        microseconds wide, and what is under test is the handler's response to
        losing it, not the scheduler's ability to reproduce it.
        """
        page = await _seed_foreign_page(editor_client, slug="raced")
        await editor_client.post(ARTICLES, json={"page_id": page.id})

        async def _sees_nothing(db, page_id):
            return None

        monkeypatch.setattr(service, "get_by_page", _sees_nothing)

        response = await editor_client.post(ARTICLES, json={"page_id": page.id})

        assert response.status_code == 409
        assert "already an article" in response.json()["detail"]
