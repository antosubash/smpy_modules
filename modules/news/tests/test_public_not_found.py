"""The site's own 404 for an article a reader cannot see (#248).

Every cause — a slug that was never an article, a draft, a trashed article, one
scheduled but not yet live — answers with pagebuilder's ``PublicNotFound`` page
in the site's frame, identically, and nothing caches it. Without pagebuilder
mounted the host's error page answers, with the same cache headers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from factories import make_article
from httpx import AsyncClient
from news import redirects
from news.models import ArticleStatus
from site_app import COMPONENT, FOOTER, HEADER, INERTIA, set_layout, site_client

pytestmark = pytest.mark.asyncio

_FRAME = {"locale", "home_href", "site_name", "copy", "layout_header", "layout_footer", "site_nav"}


@pytest.fixture
async def site():
    async for client in site_client():
        yield client


@pytest.fixture
async def bilingual_site(bilingual):
    async for client in site_client(locales=bilingual):
        yield client


def _session(client: AsyncClient):
    return client.db_state.session_factory()  # type: ignore[attr-defined]


async def _seed_every_cause(client: AsyncClient, locale: str = "en") -> list[str]:
    """One slug per reason a reader gets the 404, in ``locale``."""
    async with _session(client) as db:
        await make_article(db, slug="a-draft", status=ArticleStatus.DRAFT, locale=locale)
        await make_article(
            db, slug="in-review", status=ArticleStatus.SUBMITTED_FOR_REVIEW, locale=locale
        )
        trashed = await make_article(db, slug="trashed", locale=locale)
        trashed.deleted_at = datetime.now(UTC)
        later = await make_article(db, slug="later", status=ArticleStatus.DRAFT, locale=locale)
        later.publish_at = datetime.now(UTC) + timedelta(days=2)
        db.add_all([trashed, later])
        await db.commit()
    return ["never-existed", "a-draft", "in-review", "trashed", "later"]


async def test_every_cause_gets_the_same_site_page(site: AsyncClient) -> None:
    await set_layout(site)
    slugs = await _seed_every_cause(site)
    bodies = []
    for slug in slugs:
        response = await site.get(f"/news/{slug}", headers=INERTIA)
        assert response.status_code == 404, (slug, response.text)
        page = response.json()
        assert page["component"] == COMPONENT
        assert response.headers["Cache-Control"] == "no-store"
        assert "ETag" not in response.headers
        assert response.headers["Content-Language"] == "en"
        bodies.append({k: v for k, v in page["props"].items() if k in _FRAME})
    # No oracle: nothing in the answer tells a draft from a typo.
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["layout_header"] == HEADER
    assert bodies[0]["layout_footer"] == FOOTER
    assert bodies[0]["home_href"] == "/"
    assert bodies[0]["site_name"] == "Field Notes"
    assert bodies[0]["copy"]["not_found"]["title"] == "This page doesn't exist"


async def test_a_full_document_is_the_page_in_its_language(site: AsyncClient) -> None:
    accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    response = await site.get("/news/nope", headers={"Accept": accept})
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert '<html lang="en"' in response.text
    assert COMPONENT in response.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "accept",
    ["application/json", "application/json, text/html;q=0", "application/json, text/html;q=0.5"],
)
async def test_a_json_caller_still_gets_json(site: AsyncClient, accept: str) -> None:
    response = await site.get("/news/nope", headers={"Accept": accept})
    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}
    assert response.headers["Cache-Control"] == "no-store"


async def test_an_inertia_visit_gets_the_page_whatever_it_accepts(site: AsyncClient) -> None:
    response = await site.get("/news/nope", headers={**INERTIA, "Accept": "application/json"})
    assert response.status_code == 404
    assert response.json()["component"] == COMPONENT


async def test_german_addresses_get_the_german_page(bilingual_site: AsyncClient) -> None:
    slugs = await _seed_every_cause(bilingual_site, locale="de")
    bodies = []
    for slug in slugs:
        response = await bilingual_site.get(f"/de/news/{slug}", headers=INERTIA)
        assert response.status_code == 404, (slug, response.text)
        assert response.headers["Content-Language"] == "de"
        bodies.append(response.json()["props"])
    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["locale"] == "de"
    # The address's language, not the reader's UI language.
    assert bodies[0]["copy"]["not_found"]["title"] == "Diese Seite gibt es nicht"
    full = await bilingual_site.get("/de/news/nope", headers={"Accept": "text/html"})
    assert '<html lang="de"' in full.text


async def test_a_renamed_articles_old_address_still_redirects(site: AsyncClient) -> None:
    async with _session(site) as db:
        article = await make_article(db, slug="new-name")
        await redirects.record(
            db, article_id=article.id, old_slug="old-name", new_slug="new-name", locale="en"
        )
        await db.commit()
    moved = await site.get("/news/old-name", headers=INERTIA)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/news/new-name"
    # A published article is still served as before.
    assert (await site.get("/news/new-name", headers=INERTIA)).status_code == 200


async def test_an_archive_page_past_the_end_is_the_same_page(site: AsyncClient) -> None:
    for query in ("?page=2", "?page=99999999999"):
        response = await site.get(f"/news/{query}", headers=INERTIA)
        assert response.status_code == 404, query
        assert response.json()["component"] == COMPONENT
        assert response.headers["Cache-Control"] == "no-store"
    plain = await site.get("/news/?page=2", headers={"Accept": "application/json"})
    assert plain.json() == {"detail": "No such page"}


async def test_without_pagebuilder_the_host_page_answers_uncached(anon_client) -> None:
    """News alone: no site frame, so the host's error page, still ``no-store``."""
    response = await anon_client.get("/news/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Article not found"}
    assert response.headers["Cache-Control"] == "no-store"


async def test_with_pagebuilder_installed_but_not_its_contract(site, monkeypatch) -> None:
    """An older pagebuilder without ``contracts.public``: news' own 404."""
    from pagebuilder import contracts

    monkeypatch.delattr(contracts, "public")
    response = await site.get("/news/nope", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


async def test_feed_is_unaffected(site: AsyncClient) -> None:
    assert (await site.get("/news/feed.xml")).status_code == 200
