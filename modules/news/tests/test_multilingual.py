"""An article in more than one language.

News gets the language dimension almost for free, and that is the point: an
article *is* a pagebuilder page, so its language is the page's language and
there is no second copy of it here to drift. What this module has to get right
is the three places that are its own — the public address an article reports,
the listing filter a feed block passes, and the sidecar row a translation
needs alongside the translated page.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service
from news.integrations.pagebuilder import PageStatus

pytestmark = pytest.mark.asyncio

API = "/api/news"


async def _article(db, slug: str, *, locale: str | None = None, **kwargs):
    page = await make_page(db, slug=slug, title=slug, locale=locale)
    article = await service.create(
        db,
        page_id=page.id,
        category=kwargs.pop("category", ""),
        published_at=kwargs.pop("published_at", None),
        author=kwargs.pop("author", ""),
    )
    await db.commit()
    return page, article


class TestPublicAddress:
    async def test_the_default_language_keeps_the_bare_prefix(
        self, editor_client, bilingual
    ) -> None:
        """No article URL that already exists changes when a site adds a
        second language."""
        async with editor_client.db_state.session_factory() as db:
            await _article(db, "field-notes", locale="en")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"

    async def test_another_language_is_prefixed(self, editor_client, bilingual) -> None:
        async with editor_client.db_state.session_factory() as db:
            await _article(db, "feldnotizen", locale="de")

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
            await _article(db, "english-one", locale="en")
            await _article(db, "german-one", locale="de")

        body = (await editor_client.get(f"{API}/articles?locale=de")).json()

        assert [item["slug"] for item in body["items"]] == ["german-one"]

    async def test_the_admin_list_shows_every_language(
        self, editor_client, bilingual
    ) -> None:
        """An editor looking for an article should not have to guess which
        translation they filed the headline under."""
        async with editor_client.db_state.session_factory() as db:
            await _article(db, "english-one", locale="en")
            await _article(db, "german-one", locale="de")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert len(body["items"]) == 2

    async def test_an_unconfigured_language_filters_nothing(
        self, editor_client, bilingual
    ) -> None:
        """The value arrives from a query string; a link to a language the site
        has since dropped should show the list, not an error."""
        async with editor_client.db_state.session_factory() as db:
            await _article(db, "english-one", locale="en")

        response = await editor_client.get(f"{API}/articles?locale=fr")

        assert response.status_code == 200
        assert len(response.json()["items"]) == 1


class TestTheGroupIsListable:
    async def test_the_switcher_asks_the_ordinary_listing(
        self, editor_client, bilingual
    ) -> None:
        """Through the listing rather than a route of its own, so it inherits
        the visibility rule instead of restating it."""
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")
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
            published, _ = await _article(db, "live", locale="en")
            await make_page(
                db, slug="entwurf", title="Entwurf", status=PageStatus.DRAFT, locale="de"
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
            await _article(db, "field-notes")

        body = (await editor_client.get(f"{API}/articles")).json()

        assert body["items"][0]["url"] == "/news/field-notes"


class TestPublicRoutesAreMountedPerLanguage:
    """``on_startup`` mounts one viewer per content locale.

    A router each rather than a ``/{locale}`` path parameter: a parameter
    matches *any* first segment, and the public-route registry exempts by
    string prefix — so the exemption would have to be widened to something
    that no longer describes what is public.
    """

    def _paths(self, client) -> set[str]:
        # Read off the OpenAPI schema rather than walking ``app.routes``:
        # FastAPI 0.136 wraps an included router in an opaque
        # ``_IncludedRouter`` with no ``path``, so the route list no longer
        # answers "what is mounted where" — the schema does.
        return set(client.app.openapi()["paths"])

    async def test_each_language_gets_its_own(self, bilingual_public_client) -> None:
        paths = self._paths(bilingual_public_client)

        assert "/news/{slug}" in paths
        assert "/de/news/{slug}" in paths

    async def test_the_default_languages_prefix_only_redirects(
        self, bilingual_public_client
    ) -> None:
        """Serving the article at both would put one document at two
        addresses; 404 would be correct and useless."""
        assert "/en/news/{slug}" in self._paths(bilingual_public_client)

        response = await bilingual_public_client.get(
            "/en/news/budget", follow_redirects=False
        )

        assert response.status_code == 301
        assert response.headers["location"] == "/news/budget"


class TestWhichSlugsAreArticles:
    """The query behind both the viewer and the claim news registers."""

    async def test_it_answers_within_one_language(self, db, bilingual) -> None:
        from news.endpoints.public_views import published_article_slugs

        await _article(db, "budget", locale="en")

        assert await published_article_slugs(db, ["budget"], "en") == {"budget"}
        assert await published_article_slugs(db, ["budget"], "de") == set()

    async def test_the_claim_carries_the_language_prefix(self, db, bilingual) -> None:
        """The address a crawler is sent to and the address the admin list
        shows come from one function, so they cannot disagree."""
        from news.endpoints.public_views import slug_claim

        await _article(db, "budget", locale="de")

        assert await slug_claim()(db, ["budget"], "de") == {"budget": "/de/news/budget"}
        assert await slug_claim()(db, ["budget"], "en") == {}
