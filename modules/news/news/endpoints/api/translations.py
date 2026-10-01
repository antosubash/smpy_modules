"""Starting an article's counterpart in another language.

An article's language is fixed for its lifetime — moving one between languages
would strand its slug in the old one and orphan every redirect pointing at it —
so there is no "change language". There is this: a **sibling article** sharing a
``translation_group``, which is what the editor's language switcher lists and
what ``GET /articles?translation_group=…`` returns.

This used to write a pagebuilder *page*, because an article's body lived in one:
two rows in two modules, in one transaction, and an article that existed as only
one of them was not something either module could repair on its own. The body is
a column here now, so a translation is one insert.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from simple_module_db import get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.content import ArticlesService
from news.contracts.schemas import ArticleRead, ArticleTranslationCreate
from news.endpoints.api._deps import checked_locale, read_one, require_edit
from news.models import NewsArticle

router = APIRouter(dependencies=[require_edit])


@router.post(
    "/articles/{article_id}/translations",
    response_model=ArticleRead,
    status_code=201,
)
async def translate_article(
    article_id: int,
    body: ArticleTranslationCreate,
    db: AsyncSession = Depends(get_db),
) -> ArticleRead:
    """Start this article's counterpart in another language.

    The new article is seeded from the source rather than left blank. A
    translation belongs in the same category, under the same byline and on the
    same date as what it translates — those are facts about the story, not about
    the language it is told in, and asking for them again would invite them to
    drift apart between languages. It is *undated* only if the source is, and
    ``pinned`` and ``show_in_feed`` come across too, so a pinned story stays
    pinned in every language it is published in.

    It starts as a draft, always. Publishing untranslated copy at a URL that did
    not exist a second earlier is the one outcome worse than no translation.

    The slug defaults to the source's own, which is free unless something else
    in the target language took it: slugs are unique per ``(locale, slug)``, so
    ``/news/budget`` and ``/de/news/budget`` do not collide.
    """
    # Through ``get_article`` rather than a plain read, because it applies the
    # rule every other write path applies: a trashed article is a 404 here, and
    # translating one would put a live sibling behind something the author
    # believes they deleted.
    service_ = ArticlesService(db)
    article = await service_.get_article(article_id)

    # Required here, unlike on create: a translation is *into* a language, so
    # there is no sensible default to fall back to.
    locale = checked_locale(body.locale)
    if locale is None:  # pragma: no cover — the DTO requires a non-empty value
        raise HTTPException(status_code=422, detail="A locale is required.")

    # Checked here rather than left to the unique index on
    # ``(translation_group, locale)``, which is the real guarantee: the
    # IntegrityError that index raises surfaces as "Slug already in use", and a
    # translator told that about a slug nobody typed has no idea what happened.
    group = article.translation_group
    if await _has_locale(db, group, locale):
        raise HTTPException(
            status_code=409,
            detail=f"This article already has a {locale} translation (check the trash).",
        )

    translated = await service_.create(
        title=body.title or article.title,
        slug=body.slug or article.slug,
        locale=locale,
        translation_group=group,
        category=article.category,
        author=article.author,
        published_at=article.published_at,
    )
    await service.update(
        db, translated, pinned=article.pinned, show_in_feed=article.show_in_feed
    )
    return await read_one(db, translated.id or 0)


async def _has_locale(db: AsyncSession, group: str, locale: str) -> bool:
    """Whether the group already holds an article in this language.

    Drafts count, and so does the trash: ``(translation_group, locale)`` is
    unique over every row, trashed ones included, so a binned German sibling
    still blocks a new one and the insert would fail on the index with a "Slug
    already in use" that names nothing the translator typed.
    """
    return (
        await db.scalar(
            select(NewsArticle.id)
            .where(
                NewsArticle.translation_group == group,
                NewsArticle.locale == locale,
            )
            .limit(1)
        )
    ) is not None
