"""An article in more than one language.

This used to come almost for free: an article *was* a pagebuilder page, so its
language was the page's and there was no second copy of it here to drift. The
article owns its content now, so it owns its language too — and every one of
these properties is news' own to keep.

This file is the *data* half: what language an article is in, what a listing
shows, and what a group holds. The addressing half — which routes exist, which
language a slug resolves in, which redirect an old URL honours — is in
``test_locale_addressing``, and starting a translation is in
``test_article_translations``. Three files rather than one for the repo's
300-line cap, split where the seams already were.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

API = "/api/news"


class TestPublicAddress:
    async def test_the_default_language_keeps_the_bare_prefix(
        self, editor_client, bilingual
    ) -> None:
        """No article URL that already exists changes when a site adds a
        second language."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="field-notes", locale="en")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"

    async def test_another_language_is_prefixed(self, editor_client, bilingual) -> None:
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="feldnotizen", locale="de")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert body["items"][0]["url"] == "/de/news/feldnotizen"
        assert body["items"][0]["locale"] == "de"


class TestListingFilter:
    async def test_a_feed_sees_only_its_own_language(
        self, editor_client, bilingual
    ) -> None:
        """A feed block on a German page passes ``de``. An English card in a
        German list is worse than no card."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="english-one", locale="en")
            await make_article(db, slug="german-one", locale="de")

        body = (await editor_client.get(f"{API}/articles?locale=de")).json()

        assert [item["slug"] for item in body["items"]] == ["german-one"]

    async def test_the_admin_list_shows_every_language(
        self, editor_client, bilingual
    ) -> None:
        """An editor looking for an article should not have to guess which
        translation they filed the headline under."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="english-one", locale="en")
            await make_article(db, slug="german-one", locale="de")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert len(body["items"]) == 2

    async def test_an_unconfigured_language_filters_nothing(
        self, editor_client, bilingual
    ) -> None:
        """The value arrives from a query string; a link to a language the site
        has since dropped should show the list, not an error."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="english-one", locale="en")

        response = await editor_client.get(f"{API}/articles?locale=fr")

        assert response.status_code == 200
        assert len(response.json()["items"]) == 1


class TestSlugsAreUniquePerLanguage:
    """``/news/budget`` and ``/de/news/budget`` are two documents.

    The whole reason the unique index is on ``(locale, slug)`` rather than on
    ``slug`` alone: forcing the German article to pick a different word would
    make the URL a workaround for a schema decision.
    """

    async def test_two_languages_can_hold_the_same_slug(
        self, editor_client, bilingual
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="budget", locale="en")
            await make_article(db, slug="budget", locale="de")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert sorted(item["url"] for item in body["items"]) == [
            "/de/news/budget",
            "/news/budget",
        ]

    async def test_the_derived_slug_only_avoids_its_own_language(
        self, editor_client, bilingual
    ) -> None:
        """A translator should not be handed ``budget-2`` for a word nothing in
        their language has claimed."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="budget", title="Budget", locale="en")

        created = await editor_client.post(
            f"{API}/articles", json={"title": "Budget", "locale": "de"}
        )

        assert created.status_code == 201, created.text
        assert created.json()["slug"] == "budget"


class TestCreatingInALanguage:
    async def test_an_article_is_created_in_the_language_asked_for(
        self, editor_client, bilingual
    ) -> None:
        created = await editor_client.post(
            f"{API}/articles", json={"title": "Feldnotizen", "locale": "de"}
        )

        assert created.status_code == 201, created.text
        assert created.json()["locale"] == "de"
        assert created.json()["url"] == "/de/news/feldnotizen"

    async def test_no_language_means_the_sites_default(
        self, editor_client, bilingual
    ) -> None:
        """What every caller written before there was such a thing as a
        language means, and what keeps a monolingual host from having to say
        ``en`` on every create."""
        created = await editor_client.post(f"{API}/articles", json={"title": "Notes"})

        assert created.json()["locale"] == "en"

    async def test_an_unconfigured_language_is_refused(
        self, editor_client, bilingual
    ) -> None:
        """A write is refused rather than quietly filed under the default: the
        locale is fixed for the article's lifetime and is part of its address,
        so guessing would put it at a URL nobody can move it off."""
        response = await editor_client.post(
            f"{API}/articles", json={"title": "Notes", "locale": "fr"}
        )

        assert response.status_code == 422
        assert "fr" in response.json()["detail"]


class TestTheGroupIsListable:
    async def test_the_switcher_asks_the_ordinary_listing(
        self, editor_client, bilingual
    ) -> None:
        """Through the listing rather than a route of its own, so it inherits
        the visibility rule instead of restating it."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")
        translated = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        body = (
            await editor_client.get(
                f"{API}/articles?translation_group={translated['translation_group']}"
            )
        ).json()

        assert sorted(item["locale"] for item in body["items"]) == ["de", "en"]

    async def test_a_reader_without_edit_sees_only_published_ones(
        self, viewer_client, bilingual
    ) -> None:
        async with viewer_client.db_state.session_factory() as db:
            published = await make_article(db, slug="live", locale="en")
            await make_article(
                db,
                slug="entwurf",
                locale="de",
                status=ArticleStatus.DRAFT,
                translation_group=published.translation_group,
            )

        body = (
            await viewer_client.get(
                f"{API}/articles?translation_group={published.translation_group}"
            )
        ).json()

        assert [item["slug"] for item in body["items"]] == ["live"]


class TestMonolingualSitesAreUnaffected:
    async def test_the_url_carries_no_prefix(self, editor_client) -> None:
        """No ``bilingual`` fixture: one language, and every article URL is
        exactly what it was before there was such a thing as a language."""
        async with editor_client.db_state.session_factory() as db:
            await make_article(db, slug="field-notes")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"


