"""Every news slug lookup names its language (#131).

``ArticlesService.get_by_slug_published`` used to fall back to the default
language when no locale was passed. Pagebuilder's equivalent has always required
one, and CLAUDE.md's rule is that every slug lookup takes a locale: a lookup
that does not is how ``/de/news/x`` starts serving the English article.
"""

from __future__ import annotations

import pytest
from factories import make_article
from news import locales
from news.content import ArticlesService
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio


class TestEverySlugLookupNamesItsLanguage:
    """``get_by_slug_published`` has no default locale (#131).

    A fallback to the default language is exactly the failure this file exists
    to pin: a caller that forgot the argument would be handed the English
    article at a German address, and nothing would look wrong.
    """

    async def test_the_locale_cannot_be_omitted(self, db) -> None:
        with pytest.raises(TypeError):
            await ArticlesService(db).get_by_slug_published("field-notes")  # type: ignore[call-arg]

    async def test_a_german_lookup_never_returns_the_english_article(
        self, db, bilingual
    ) -> None:
        """The German translation exists at the same slug but is still a draft,
        so the only *published* ``budget`` is English. A German lookup has to
        come back empty rather than reach across to it."""
        await make_article(db, slug="budget", title="Budget", locale="en")
        await make_article(
            db, slug="budget", title="Haushalt", locale="de",
            status=ArticleStatus.DRAFT, publish_body=False,
        )
        service = ArticlesService(db)

        assert await service.get_by_slug_published("budget", "de") is None
        english = await service.get_by_slug_published("budget", "en")
        assert english is not None and english.locale == "en"

    async def test_a_monolingual_site_looks_up_in_its_default_language(
        self, db
    ) -> None:
        """What keeps a monolingual host working: it names its one language."""
        await make_article(db, slug="field-notes")

        found = await ArticlesService(db).get_by_slug_published(
            "field-notes", locales.default()
        )

        assert found is not None
        assert found.locale == locales.default()
