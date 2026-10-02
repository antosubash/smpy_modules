"""Lenient ``?page=`` on public archives, and ``<html lang>`` on public pages."""

from __future__ import annotations

import pytest
from factories import make_article
from news.models import NewsCategory

pytestmark = pytest.mark.asyncio

NEWS = "/news"
INERTIA = {"X-Inertia": "true"}


class TestLenientPage:
    @pytest.mark.parametrize("raw", ["0", "-1", "abc", "", "1.5"])
    @pytest.mark.parametrize("path", ["/", "/category/notes", "/tag/x", "/author/ann"])
    async def test_a_bad_page_is_page_one(self, anon_client, path, raw) -> None:
        async with anon_client.db_state.session_factory() as db:
            db.add(NewsCategory(name="notes", slug="notes"))
            await make_article(db, slug="one", title="one", category="notes")

        response = await anon_client.get(f"{NEWS}{path}?page={raw}", headers=INERTIA)

        # An empty tag or byline has no page 2, but page 1 of it is a 404 only
        # past the end; "page 1 of nothing" is the existing empty-archive rule.
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            assert response.json()["props"]["page"] == 1

    @pytest.mark.parametrize("raw", ["0", "-1", "abc"])
    async def test_the_index_with_articles_is_page_one(self, anon_client, raw) -> None:
        async with anon_client.db_state.session_factory() as db:
            await make_article(db, slug="one", title="one")

        response = await anon_client.get(f"{NEWS}/?page={raw}", headers=INERTIA)

        assert response.status_code == 200
        assert response.json()["props"]["page"] == 1

    @pytest.mark.parametrize("path", ["/", "/category/notes"])
    async def test_a_huge_page_is_a_404(self, anon_client, path) -> None:
        response = await anon_client.get(f"{NEWS}{path}?page=99999999999999999999", headers=INERTIA)

        assert response.status_code == 404

    async def test_a_page_past_the_end_is_still_a_404(self, anon_client) -> None:
        response = await anon_client.get(f"{NEWS}/?page=900", headers=INERTIA)

        assert response.status_code == 404


class TestHtmlLang:
    async def test_a_german_article_is_served_as_german(self, bilingual_public_client) -> None:
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="haushalt", title="Haushalt", locale="de")

        body = (await bilingual_public_client.get("/de/news/haushalt")).text

        assert '<html lang="de" data-shell-lang="en">' in body

    async def test_the_default_language_stays_english(self, bilingual_public_client) -> None:
        async with bilingual_public_client.db_state.session_factory() as db:
            await make_article(db, slug="budget", title="Budget", locale="en")

        body = (await bilingual_public_client.get("/news/budget")).text

        assert '<html lang="en" data-shell-lang="en">' in body
