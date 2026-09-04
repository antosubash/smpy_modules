"""Starting an article's counterpart in another language.

Split from ``test_multilingual`` for the repo's 300-line cap. Two writes in one
transaction: the translated *page* is pagebuilder's, the sidecar row carrying
category, byline and date is news', and an article that exists as only one of
those is not something either module can repair on its own.
"""

from __future__ import annotations

import pytest
from conftest import make_page
from news import service

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


class TestTranslatingAnArticle:
    async def test_it_creates_the_page_and_the_sidecar_together(
        self, editor_client, bilingual
    ) -> None:
        """An article that exists as only one of those is not something either
        module can repair on its own."""
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en", category="Field")

        response = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert response.status_code == 201, response.text
        created = response.json()
        assert created["locale"] == "de"
        assert created["id"] != article.id
        assert created["page_id"] != article.page_id

    async def test_the_story_facts_come_across(self, editor_client, bilingual) -> None:
        """Category, byline, date, pin and feed membership are facts about the
        story, not about the language it is told in — asking for them again
        would invite them to drift between languages."""
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(
                db, "budget", locale="en", category="Field", author="R. Vogel"
            )
            await service.update(db, article, pinned=True)
            await db.commit()

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["category"] == "Field"
        assert created["author"] == "R. Vogel"
        assert created["pinned"] is True

    async def test_it_starts_as_a_draft(self, editor_client, bilingual) -> None:
        """Publishing untranslated copy at a URL that did not exist a second
        earlier is the one outcome worse than no translation."""
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["page_status"] == "draft"

    async def test_it_reuses_the_slug_under_the_new_prefix(
        self, editor_client, bilingual
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["url"] == "/de/news/budget"

    async def test_a_second_one_in_the_same_language_is_refused(
        self, editor_client, bilingual
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")
        await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        again = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert again.status_code == 409

    async def test_an_unconfigured_language_is_refused(
        self, editor_client, bilingual
    ) -> None:
        """422 naming what is configured, from news rather than from inside
        the page write — the error should talk about the field the author
        filled in, not about a page nobody in the request has seen."""
        async with editor_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")

        response = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "fr"}
        )

        assert response.status_code == 422
        assert "fr" in response.json()["detail"]

    async def test_it_needs_pagebuilders_edit_too(
        self, news_only_client, bilingual
    ) -> None:
        """Creating a translation writes a *page*. News does not get to route
        around the editor → publisher separation pagebuilder maintains."""
        async with news_only_client.db_state.session_factory() as db:
            _, article = await _article(db, "budget", locale="en")

        response = await news_only_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert response.status_code == 403

    async def test_a_missing_article_is_a_404(self, editor_client, bilingual) -> None:
        response = await editor_client.post(
            f"{API}/articles/9999/translations", json={"locale": "de"}
        )

        assert response.status_code == 404
