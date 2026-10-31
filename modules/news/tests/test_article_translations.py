"""Starting an article's counterpart in another language.

Split from ``test_multilingual`` for the repo's 300-line cap.

This used to be two writes in two modules — the translated *page* was
pagebuilder's and the sidecar row carrying category, byline and date was news' —
and an article that existed as only one of those was not something either module
could repair. The body is a column here now, so a translation is one insert, and
the properties worth pinning are about what it inherits and what it refuses.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

API = "/api/news"


class TestTranslatingAnArticle:
    async def test_it_creates_a_sibling_in_the_same_group(
        self, editor_client, bilingual
    ) -> None:
        """A sibling sharing a ``translation_group``, not a copy pointing back
        at an original: translations have no parent, so deleting the English
        one must not orphan or re-parent the rest."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(
                db, slug="budget", locale="en", category="Field"
            )

        response = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert response.status_code == 201, response.text
        created = response.json()
        assert created["locale"] == "de"
        assert created["id"] != article.id
        assert created["translation_group"] == article.translation_group

    async def test_the_story_facts_come_across(self, editor_client, bilingual) -> None:
        """Category, byline, date, pin and feed membership are facts about the
        story, not about the language it is told in — asking for them again
        would invite them to drift between languages."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(
                db,
                slug="budget",
                locale="en",
                category="Field",
                author="R. Vogel",
                pinned=True,
            )

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
            article = await make_article(db, slug="budget", locale="en")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["status"] == ArticleStatus.DRAFT.value

    async def test_it_reuses_the_slug_under_the_new_prefix(
        self, editor_client, bilingual
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["url"] == "/de/news/budget"

    async def test_the_headline_carries_over_untranslated(
        self, editor_client, bilingual
    ) -> None:
        """A more useful starting point for a translator than a blank field,
        and it makes what still needs doing obvious in the list."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", title="The budget")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations", json={"locale": "de"}
            )
        ).json()

        assert created["title"] == "The budget"

    async def test_an_explicit_slug_and_title_are_honoured(
        self, editor_client, bilingual
    ) -> None:
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")

        created = (
            await editor_client.post(
                f"{API}/articles/{article.id}/translations",
                json={"locale": "de", "slug": "haushalt", "title": "Der Haushalt"},
            )
        ).json()

        assert created["url"] == "/de/news/haushalt"
        assert created["title"] == "Der Haushalt"

    async def test_a_second_one_in_the_same_language_is_refused(
        self, editor_client, bilingual
    ) -> None:
        """A double submit or a stale tab would otherwise produce two German
        siblings, and every ``hreflang`` list would start contradicting
        itself."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")
        await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        again = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert again.status_code == 409
        # Named for what actually collided. The unique index behind this would
        # surface as "Slug already in use", which is about a slug nobody typed.
        assert "de" in again.json()["detail"]

    async def test_an_unconfigured_language_is_refused(
        self, editor_client, bilingual
    ) -> None:
        """422 naming what is configured, so the error talks about the field
        the author filled in."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")

        response = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "fr"}
        )

        assert response.status_code == 422
        assert "fr" in response.json()["detail"]

    async def test_it_needs_news_edit(self, viewer_client, bilingual) -> None:
        """Creating a translation creates an article. A reader who may not
        write one does not get to write one in German."""
        async with viewer_client.db_state.session_factory() as db:
            article = await make_article(db, slug="budget", locale="en")

        response = await viewer_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert response.status_code == 403

    async def test_a_missing_article_is_a_404(self, editor_client, bilingual) -> None:
        response = await editor_client.post(
            f"{API}/articles/9999/translations", json={"locale": "de"}
        )

        assert response.status_code == 404

    async def test_a_trashed_article_is_a_404_too(
        self, editor_client, bilingual
    ) -> None:
        """The rule every other write path applies. Translating one would put a
        live sibling behind something the author believes they deleted."""
        async with editor_client.db_state.session_factory() as db:
            article = await make_article(db, slug="binned", locale="en")
            await ArticlesService(db).trash(article.id)
            await db.commit()

        response = await editor_client.post(
            f"{API}/articles/{article.id}/translations", json={"locale": "de"}
        )

        assert response.status_code == 404
