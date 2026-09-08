"""Locale is part of every address.

Split from ``test_multilingual``, which is about the *data* — what language an
article is in, which ones a listing shows, how a translation is started. This is
about the *addresses* that follow from it: which routes exist, which language a
slug is resolved in, and which redirect an old URL honours.

The rule the whole file exists to pin: every slug lookup, redirect and public
route takes a locale. One that does not is how ``/de/news/x`` starts serving the
English article — a failure that is invisible until someone reads the wrong
language and never reports it.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import locales, redirects
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio


class TestRoutesAreMountedPerLanguage:
    """``on_startup`` mounts one public router per content locale.

    A router each rather than a ``/{locale}`` path parameter: a parameter
    matches *any* first segment, and the public-route registry exempts by
    string prefix — so the exemption would have to be widened to something that
    no longer describes what is public.
    """

    def _paths(self, client) -> set[str]:
        # Read off the OpenAPI schema rather than walking ``app.routes``:
        # FastAPI 0.136 wraps an included router in an opaque
        # ``_IncludedRouter`` with no ``path``, so the route list no longer
        # answers "what is mounted where" — the schema does.
        return set(client.app.openapi()["paths"])

    async def test_each_language_gets_its_own_viewer(
        self, bilingual_public_client
    ) -> None:
        paths = self._paths(bilingual_public_client)

        assert "/news/{slug}" in paths
        assert "/de/news/{slug}" in paths

    async def test_the_archive_is_mounted_per_language_too(
        self, bilingual_public_client
    ) -> None:
        """The reading surface, not just the leaf. An archive that existed only
        in the default language would leave every German article reachable but
        unbrowsable."""
        paths = self._paths(bilingual_public_client)

        assert {"/de/news/", "/de/news/category/{slug}", "/de/news/tag/{slug}"} <= paths

    async def test_the_feed_is_per_language_and_the_sitemap_is_not(
        self, bilingual_public_client
    ) -> None:
        """A subscription is a reading habit, so each language gets its own
        river. A sitemap is one document telling a crawler what exists, so there
        is one — publishing it twice would be duplicate content pointing at
        duplicate content."""
        paths = self._paths(bilingual_public_client)

        assert {"/news/feed.xml", "/de/news/feed.xml"} <= paths
        assert "/news/sitemap.xml" in paths
        assert "/de/news/sitemap.xml" not in paths

    async def test_the_default_languages_prefix_only_redirects(
        self, bilingual_public_client
    ) -> None:
        """Serving the article at both would put one document at two addresses;
        404 would be correct and useless."""
        assert "/en/news/{slug}" in self._paths(bilingual_public_client)

        response = await bilingual_public_client.get(
            "/en/news/budget", follow_redirects=False
        )

        assert response.status_code == 301
        assert response.headers["location"] == "/news/budget"


class TestTheViewerResolvesWithinOneLanguage:
    async def test_a_slug_only_answers_in_its_own_language(self, db, bilingual) -> None:
        await make_article(db, slug="budget", locale="en")
        service = ArticlesService(db)

        assert await service.get_by_slug_published("budget", "en") is not None
        assert await service.get_by_slug_published("budget", "de") is None

    async def test_two_languages_serve_their_own_article_at_one_slug(
        self, db, bilingual
    ) -> None:
        """The point of ``(locale, slug)`` being the unique key rather than
        ``slug``: these are two documents, not a collision."""
        await make_article(db, slug="budget", title="Budget", locale="en")
        await make_article(db, slug="budget", title="Haushalt", locale="de")
        service = ArticlesService(db)

        english = await service.get_by_slug_published("budget", "en")
        german = await service.get_by_slug_published("budget", "de")

        assert (english.title, german.title) == ("Budget", "Haushalt")


class TestRedirectsAreScopedToOneLanguage:
    """An old German address forwarding to the English article would answer
    "where did my page go" with someone else's article."""

    async def test_the_same_old_slug_forwards_differently_per_language(
        self, db, bilingual
    ) -> None:
        english = await make_article(db, slug="new-en", locale="en")
        german = await make_article(db, slug="new-de", locale="de")
        await redirects.record(
            db, article_id=english.id, old_slug="retired", new_slug="new-en", locale="en"
        )
        await redirects.record(
            db, article_id=german.id, old_slug="retired", new_slug="new-de", locale="de"
        )

        assert await redirects.resolve(db, "retired", "en") == "new-en"
        assert await redirects.resolve(db, "retired", "de") == "new-de"

    async def test_a_redirect_does_not_leak_into_another_language(
        self, db, bilingual
    ) -> None:
        """Two languages can legitimately have retired the same word, and only
        one of them recorded a redirect for it."""
        english = await make_article(db, slug="new-en", locale="en")
        await redirects.record(
            db, article_id=english.id, old_slug="retired", new_slug="new-en", locale="en"
        )

        assert await redirects.resolve(db, "retired", "de") is None

    async def test_renaming_in_one_language_leaves_the_other_alone(
        self, db, bilingual
    ) -> None:
        """The deletes ``record`` performs first are locale-scoped too, so
        clearing the German article's path never drops the English redirect from
        the same word."""
        english = await make_article(db, slug="budget", locale="en")
        german = await make_article(db, slug="budget", locale="de")
        service = ArticlesService(db)

        await service.update(english.id, {"slug": "the-budget"})
        await service.update(german.id, {"slug": "der-haushalt"})

        assert await redirects.resolve(db, "budget", "en") == "the-budget"
        assert await redirects.resolve(db, "budget", "de") == "der-haushalt"


class TestTheViewerAdvertisesItsTranslations:
    """``hreflang``, server-rendered.

    A crawler deciding which language to index for a query does it without
    running the script, so a switch that only exists after the bundle executes
    is a switch that does not exist.
    """

    async def _pair(self, client) -> None:
        async with client.db_state.session_factory() as db:
            english = await make_article(
                db, slug="budget", title="Budget", locale="en"
            )
            await make_article(
                db,
                slug="haushalt",
                title="Haushalt",
                locale="de",
                translation_group=english.translation_group,
            )

    async def test_each_language_is_linked_from_the_other(
        self, bilingual_public_client
    ) -> None:
        await self._pair(bilingual_public_client)

        body = (await bilingual_public_client.get("/news/budget")).text

        assert 'hreflang="en"' in body
        assert 'hreflang="de"' in body
        assert "/de/news/haushalt" in body

    async def test_x_default_names_the_sites_own_language(
        self, bilingual_public_client
    ) -> None:
        """The version to serve someone whose language nobody matched. The
        site's default is the only defensible answer."""
        await self._pair(bilingual_public_client)

        body = (await bilingual_public_client.get("/de/news/haushalt")).text

        assert 'hreflang="x-default"' in body

    async def test_an_untranslated_article_advertises_nothing(
        self, bilingual_public_client
    ) -> None:
        """A lone ``hreflang`` pointing at the document itself says nothing and
        is noise in the head of every page."""
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="alone", locale="en")

        body = (await bilingual_public_client.get("/news/alone")).text

        assert "hreflang" not in body

    async def test_a_draft_translation_is_not_advertised(
        self, bilingual_public_client
    ) -> None:
        """Pointing a crawler at a 404 and offering a reader a language switch
        that dead-ends."""
        async with bilingual_public_client.db_state.session_factory() as db:
            english = await make_article(db, slug="budget", locale="en")
            await make_article(
                db,
                slug="haushalt",
                locale="de",
                status=ArticleStatus.DRAFT,
                translation_group=english.translation_group,
            )

        body = (await bilingual_public_client.get("/news/budget")).text

        assert "haushalt" not in body

    async def test_the_response_says_which_language_it_is(
        self, bilingual_public_client
    ) -> None:
        """For caches, and for anything reading the response without parsing
        the body."""
        await self._pair(bilingual_public_client)

        response = await bilingual_public_client.get("/de/news/haushalt")

        assert response.headers["Content-Language"] == "de"


class TestMonolingualSitesAreUnaffected:
    async def test_an_unqualified_lookup_means_the_default_language(self, db) -> None:
        """What every caller written before there was such a thing as a
        language means, and what keeps a monolingual host working unchanged."""
        await make_article(db, slug="field-notes")

        found = await ArticlesService(db).get_by_slug_published("field-notes")

        assert found is not None
        assert found.locale == locales.default()
