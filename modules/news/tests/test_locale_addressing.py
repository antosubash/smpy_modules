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

    async def test_only_the_default_language_has_an_alias(
        self, bilingual_public_client
    ) -> None:
        """The alias exists because the default language serves *unprefixed*,
        so ``/en/news/x`` is a second spelling of one address. ``/de/news/x`` is
        the German article's only address — bouncing it anywhere would send a
        German reader to English, which is the whole failure the prefix scheme
        exists to prevent."""
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="haushalt", locale="de")

        response = await bilingual_public_client.get(
            "/de/news/haushalt", follow_redirects=False
        )

        assert response.status_code == 200, response.text

    async def test_a_language_the_site_does_not_publish_is_not_served(
        self, bilingual_public_client
    ) -> None:
        """No router is mounted for it, so there is nothing to fall through to.

        The failure this guards is the one CLAUDE.md names by example: an
        address in a language the site does not publish must never answer with
        the default language's article. It 404s — it does not redirect to
        ``/news/budget`` either, because the two were never the same document
        and forwarding would invent an equivalence nobody declared.
        """
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="budget", title="Budget", locale="en")

        response = await bilingual_public_client.get(
            "/fr/news/budget", follow_redirects=False
        )

        assert response.status_code == 404
        assert "Budget" not in response.text
        assert "/fr/news/{slug}" not in self._paths(bilingual_public_client)

    async def test_a_configured_language_does_not_borrow_anothers_article(
        self, bilingual_public_client
    ) -> None:
        """``/de/news/budget`` 404s while only the English ``budget`` exists.

        The counterpart to the test above, and the sharper half: German *is*
        configured and its router *is* mounted, so this is the case where a
        locale-blind lookup would quietly succeed and serve English copy at a
        German URL.
        """
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="budget", title="Budget", locale="en")

        response = await bilingual_public_client.get(
            "/de/news/budget", follow_redirects=False
        )

        assert response.status_code == 404
        assert "Budget" not in response.text

    async def test_a_monolingual_site_gets_no_alias_at_all(
        self, anon_client
    ) -> None:
        """One language means the bare prefix is the only address there is, so
        there is no second spelling for an alias to collapse."""
        paths = set(anon_client.app.openapi()["paths"])

        assert "/news/{slug}" in paths
        assert "/en/news/{slug}" not in paths


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


class TestMonolingualSitesAreUnaffected:
    async def test_an_unqualified_lookup_means_the_default_language(self, db) -> None:
        """What every caller written before there was such a thing as a
        language means, and what keeps a monolingual host working unchanged."""
        await make_article(db, slug="field-notes")

        found = await ArticlesService(db).get_by_slug_published("field-notes")

        assert found is not None
        assert found.locale == locales.default()
