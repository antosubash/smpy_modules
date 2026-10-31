"""A page in more than one language.

The whole feature rests on one decision: a translation is an *ordinary page*
that happens to share a ``translation_group`` with another. Everything a page
already does — its own slug, draft, revisions, schedule and approval — is
therefore already true of a translation, and these tests are about the three
things that are genuinely new: slugs being unique per language rather than
globally, the locale-prefixed public address, and the group itself.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from locale_fixture import CONTENT_LOCALES

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


async def _page(client: AsyncClient, *, slug: str, locale: str | None = None, **extra) -> dict:
    body = {"title": extra.pop("title", slug), "slug": slug, "draft_data": {"content": []}}
    if locale is not None:
        body["locale"] = locale
    body.update(extra)
    response = await client.post(API, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client: AsyncClient, page_id: int) -> None:
    response = await client.post(f"{API}/{page_id}/publish")
    assert response.status_code == 200, response.text


class TestSlugsAreUniquePerLanguage:
    """The point of the schema change. Forcing the German page to pick a
    different word would make the URL a workaround for a database decision."""

    async def test_the_same_slug_in_two_languages_is_two_pages(
        self, bilingual_client: AsyncClient
    ) -> None:
        english = await _page(bilingual_client, slug="about", locale="en")
        german = await _page(bilingual_client, slug="about", locale="de")

        assert english["id"] != german["id"]
        assert english["locale"] == "en"
        assert german["locale"] == "de"

    async def test_the_same_slug_twice_in_one_language_still_conflicts(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _page(bilingual_client, slug="about", locale="de")

        clash = await bilingual_client.post(
            API, json={"title": "Again", "slug": "about", "locale": "de"}
        )

        assert clash.status_code == 409
        # The message names the language, or an author staring at a page list
        # that plainly contains no second "about" has nothing to go on.
        assert "de" in clash.json()["detail"]

    async def test_an_unconfigured_language_is_refused(
        self, bilingual_client: AsyncClient
    ) -> None:
        """422 naming what *is* configured. A page in a language the site does
        not serve has no address, so accepting it would create something
        unreachable."""
        response = await bilingual_client.post(
            API, json={"title": "Nope", "slug": "nope", "locale": "fr"}
        )

        assert response.status_code == 422
        assert "fr" in response.json()["detail"]

    async def test_an_omitted_language_is_the_default_one(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Every caller that predates the field — seeds included — keeps
        working, and keeps producing pages at the addresses it always did."""
        page = await _page(bilingual_client, slug="unqualified")

        assert page["locale"] == "en"


class TestPublicAddress:
    async def test_the_default_language_keeps_the_bare_prefix(
        self, bilingual_client: AsyncClient
    ) -> None:
        """The reason adding a language strands no link that already exists."""
        english = await _page(bilingual_client, slug="about", locale="en", title="About us")
        await _publish(bilingual_client, english["id"])

        response = await bilingual_client.get("/p/about")

        assert response.status_code == 200
        assert response.headers["Content-Language"] == "en"

    async def test_another_language_serves_under_its_tag(
        self, bilingual_client: AsyncClient
    ) -> None:
        german = await _page(bilingual_client, slug="about", locale="de", title="Über uns")
        await _publish(bilingual_client, german["id"])

        response = await bilingual_client.get("/de/p/about")

        assert response.status_code == 200
        assert response.headers["Content-Language"] == "de"

    async def test_a_language_a_page_is_not_in_does_not_serve_it(
        self, bilingual_client: AsyncClient
    ) -> None:
        """404, not the English page. Serving one language's document at
        another's address is the failure the whole prefix scheme prevents."""
        english = await _page(bilingual_client, slug="only-english", locale="en")
        await _publish(bilingual_client, english["id"])

        assert (await bilingual_client.get("/de/p/only-english")).status_code == 404

    async def test_the_default_languages_own_prefix_redirects(
        self, bilingual_client: AsyncClient
    ) -> None:
        """``/en/p/x`` is what anyone who has seen ``/de/p/x`` will try. Serving
        the page at both would put one document at two addresses; 404 would be
        correct and useless."""
        english = await _page(bilingual_client, slug="about", locale="en")
        await _publish(bilingual_client, english["id"])

        response = await bilingual_client.get("/en/p/about", follow_redirects=False)

        assert response.status_code == 301
        assert response.headers["location"] == "/p/about"

    async def test_an_unconfigured_prefix_is_not_a_route_at_all(
        self, bilingual_client: AsyncClient
    ) -> None:
        english = await _page(bilingual_client, slug="about", locale="en")
        await _publish(bilingual_client, english["id"])

        assert (await bilingual_client.get("/fr/p/about")).status_code == 404


class TestRedirectsAreScopedToOneLanguage:
    async def test_renaming_the_german_page_leaves_the_french_word_alone(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Two languages can legitimately retire the same word. A redirect that
        ignored the language would forward a German visitor to an English
        page."""
        german = await _page(bilingual_client, slug="ueber", locale="de")
        english = await _page(bilingual_client, slug="ueber", locale="en")
        await bilingual_client.put(f"{API}/{german['id']}", json={"slug": "ueber-uns"})
        await _publish(bilingual_client, german["id"])
        await _publish(bilingual_client, english["id"])

        moved = await bilingual_client.get("/de/p/ueber", follow_redirects=False)
        untouched = await bilingual_client.get("/p/ueber")

        assert moved.status_code == 301
        assert moved.headers["location"] == "/de/p/ueber-uns"
        # The English page never moved, so its address must still answer.
        assert untouched.status_code == 200


class TestLocalesEndpoint:
    async def test_it_reports_what_the_deployment_configured(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Served rather than compiled into the frontend, so the language
        switcher cannot offer one the API then refuses."""
        body = (await bilingual_client.get("/api/pagebuilder/locales")).json()

        assert body == {"locales": list(CONTENT_LOCALES), "default": "en"}


class TestMonolingualSitesAreUnaffected:
    async def test_no_locale_prefix_is_mounted(self, authed_client: AsyncClient) -> None:
        """With one language there is no ``/de/p/…`` to generalise from, so
        ``/en/p/…`` is a URL nobody types and a route nobody needs."""
        page = await _page(authed_client, slug="about")
        await _publish(authed_client, page["id"])

        assert (await authed_client.get("/p/about")).status_code == 200
        assert (await authed_client.get("/en/p/about")).status_code == 404
