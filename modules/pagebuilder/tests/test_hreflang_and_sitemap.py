"""Telling search engines — and readers — that the other languages exist.

Two channels, deliberately both: the ``hreflang`` links on the page itself,
and ``xhtml:link`` alternates in the sitemap. The page tags are what a crawler
sees once it has the document; the sitemap is what lets it discover a
translation nothing links to yet, which for a freshly published page is the
difference between indexed and invisible.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"
_INERTIA_HEADERS = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _published_pair(client: AsyncClient, *, publish_translation: bool = True) -> dict:
    """An English page and its German translation, both published by default."""
    source = (
        await client.post(
            API, json={"title": "About us", "slug": "about", "draft_data": {"content": []}}
        )
    ).json()
    translation = (
        await client.post(f"{API}/{source['id']}/translations", json={"locale": "de"})
    ).json()
    assert (await client.post(f"{API}/{source['id']}/publish")).status_code == 200
    if publish_translation:
        assert (await client.post(f"{API}/{translation['id']}/publish")).status_code == 200
    return {"source": source, "translation": translation}


async def _props(client: AsyncClient, path: str) -> dict:
    response = await client.get(path, headers=_INERTIA_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()["props"]


class TestHreflangOnThePage:
    async def test_each_language_names_every_other_and_itself(
        self, bilingual_client: AsyncClient
    ) -> None:
        """An hreflang set is only honoured when every member names every
        other, the page itself included."""
        await _published_pair(bilingual_client)

        props = await _props(bilingual_client, "/p/about")

        assert [a["locale"] for a in props["alternates"]] == ["de", "en", "x-default"]
        by_locale = {a["locale"]: a["url"] for a in props["alternates"]}
        assert by_locale["en"].endswith("/p/about")
        assert by_locale["de"].endswith("/de/p/about")

    async def test_x_default_points_at_the_sites_own_default(
        self, bilingual_client: AsyncClient
    ) -> None:
        """It names the version to serve someone whose language nobody
        matched, and the site's default is the only defensible answer."""
        await _published_pair(bilingual_client)

        props = await _props(bilingual_client, "/de/p/about")

        by_locale = {a["locale"]: a["url"] for a in props["alternates"]}
        assert by_locale["x-default"] == by_locale["en"]

    async def test_the_german_page_advertises_the_same_set(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _published_pair(bilingual_client)

        english = await _props(bilingual_client, "/p/about")
        german = await _props(bilingual_client, "/de/p/about")

        assert english["alternates"] == german["alternates"]

    async def test_a_draft_translation_is_not_advertised(
        self, bilingual_client: AsyncClient
    ) -> None:
        """Advertising it points a crawler at a 404 and offers a reader a
        language switch that dead-ends."""
        await _published_pair(bilingual_client, publish_translation=False)

        props = await _props(bilingual_client, "/p/about")

        # One published page in the group, so the list is dropped entirely.
        assert props["alternates"] == []

    async def test_a_monolingual_page_emits_nothing(
        self, authed_client: AsyncClient
    ) -> None:
        """A lone hreflang pointing at the page itself says nothing, and would
        be noise in the head of every document on every single-language site."""
        page = (
            await authed_client.post(
                API, json={"title": "Solo", "slug": "solo", "draft_data": {"content": []}}
            )
        ).json()
        await authed_client.post(f"{API}/{page['id']}/publish")

        props = await _props(authed_client, "/p/solo")

        assert props["alternates"] == []

    async def test_the_page_reports_its_own_language(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _published_pair(bilingual_client)

        assert (await _props(bilingual_client, "/de/p/about"))["locale"] == "de"


class TestSitemap:
    async def test_every_language_is_listed_at_its_own_address(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _published_pair(bilingual_client)

        body = (await bilingual_client.get("/sitemap.xml")).text

        assert "<loc>http://test/p/about</loc>" in body
        assert "<loc>http://test/de/p/about</loc>" in body

    async def test_each_entry_carries_its_counterparts(
        self, bilingual_client: AsyncClient
    ) -> None:
        """What lets a crawler learn the German page exists without having
        fetched the English one first."""
        await _published_pair(bilingual_client)

        body = (await bilingual_client.get("/sitemap.xml")).text

        assert 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in body
        assert body.count('hreflang="de" href="http://test/de/p/about"') == 2
        assert body.count('hreflang="x-default" href="http://test/p/about"') == 2

    async def test_an_unpublished_translation_contributes_nothing(
        self, bilingual_client: AsyncClient
    ) -> None:
        await _published_pair(bilingual_client, publish_translation=False)

        body = (await bilingual_client.get("/sitemap.xml")).text

        assert "/de/p/about" not in body
        assert "xhtml:link" not in body

    async def test_a_monolingual_sitemap_is_unchanged(
        self, authed_client: AsyncClient
    ) -> None:
        page = (
            await authed_client.post(
                API, json={"title": "Solo", "slug": "solo", "draft_data": {"content": []}}
            )
        ).json()
        await authed_client.post(f"{API}/{page['id']}/publish")

        body = (await authed_client.get("/sitemap.xml")).text

        assert "<loc>http://test/p/solo</loc>" in body
        assert "xhtml:link" not in body
