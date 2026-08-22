"""Writes to the page an article's body lives in.

An article is metadata *about* a pagebuilder page, so creating one means
creating a page too, and publishing one means publishing that page. Both used
to happen in the browser, against pagebuilder's own API, and both were the
worse for it:

* the frontend had to read pagebuilder's CSRF cookie, which its middleware only
  sets under pagebuilder's own routes — so "New article" 403'd for anyone who
  had not already visited Pages this session, and the dialog primed the cookie
  with a throwaway GET to work around it;
* creating was two requests in two transactions, so a failure of the second
  stranded an empty, articleless page that nothing would ever clean up. The
  dialog kept the first request's page id purely so a retry could adopt it.

Doing both here puts them under news' own token and, for create, in one
transaction — so a failure leaves nothing behind to adopt.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import service
from news.contracts.schemas import (
    ArticleRead,
    ArticleTranslationCreate,
    ArticleWithPageCreate,
)
from news.endpoints.api._deps import read_one_by_page, require_edit
from news.integrations.locales import content_locales, resolve_locale
from news.integrations.pagebuilder import require_page_edit, require_page_publish
from news.integrations.pages import (
    create_article_page,
    create_page_translation,
    publish_page,
)

router = APIRouter(dependencies=[require_edit])
"""``news.edit`` on every route here, plus pagebuilder's own permission for the
page write each one performs — see ``news.integrations.pagebuilder``. Moving
these writes server-side must not also move them past the editor → publisher
separation the browser path went through."""


@router.post(
    "/articles/with-page",
    response_model=ArticleRead,
    status_code=201,
    dependencies=[require_page_edit],
)
async def create_article_with_page(
    body: ArticleWithPageCreate, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Create the page and attach the article to it, in one transaction.

    The page has to exist first — an article row is metadata about one — but
    the two writes share this request's transaction, so either both land or
    neither does. That is the whole difference from the two-call version.
    """
    page = await create_article_page(
        db,
        title=body.title.strip(),
        slug=body.slug,
        locale=_checked_locale(body.locale),
    )
    await service.create(
        db,
        page_id=page.id or 0,
        category=body.category,
        published_at=body.published_at,
        author=body.author,
    )
    return await read_one_by_page(db, page.id or 0)


def _checked_locale(value: str | None) -> str | None:
    """``value`` as a content locale, or a 422 naming the configured ones.

    Rejected here rather than left to the page write so the error names the
    field the author actually filled in — a 422 from inside pagebuilder would
    talk about a page nobody in this request has seen.
    """
    if value is None:
        return None
    resolved = resolve_locale(value)
    if resolved is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{value!r} is not a content locale. "
                f"Configured: {', '.join(content_locales())}."
            ),
        )
    return resolved


@router.post(
    "/articles/{article_id}/translations",
    response_model=ArticleRead,
    status_code=201,
    dependencies=[require_page_edit],
)
async def translate_article(
    article_id: int,
    body: ArticleTranslationCreate,
    db: AsyncSession = Depends(get_db),
) -> ArticleRead:
    """Start this article's counterpart in another language.

    Two writes in one transaction, for the same reason creating an article is:
    the translated *page* is pagebuilder's, the sidecar row carrying category,
    byline and date is news', and an article that exists as only one of those
    is not something either module can repair on its own.

    The sidecar is seeded from the source rather than left blank. A
    translation belongs in the same category, under the same byline and on the
    same date as what it translates — those are facts about the story, not
    about the language it is told in. It is *undated* only if the source is.
    ``show_in_feed`` and ``pinned`` come across too, so a pinned story stays
    pinned in every language it is published in.
    """
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    locale = _checked_locale(body.locale)
    page = await create_page_translation(
        db,
        article.page_id,
        locale=locale or "",
        slug=body.slug,
        title=body.title,
    )
    translated = await service.create(
        db,
        page_id=page.id or 0,
        category=article.category,
        published_at=article.published_at,
        author=article.author,
    )
    await service.update(
        db, translated, pinned=article.pinned, show_in_feed=article.show_in_feed
    )
    return await read_one_by_page(db, page.id or 0)


@router.post(
    "/articles/{article_id}/publish",
    response_model=ArticleRead,
    dependencies=[require_page_publish],
)
async def publish_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Publish the page behind an article, from the list's row menu.

    Addressed by article rather than by page: the row menu holds an article,
    and requiring it to pass a page id would be asking the frontend to know
    which of the two ids the neighbouring module wants.
    """
    article = await service.get(db, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found.")
    await publish_page(db, article.page_id)
    return await read_one_by_page(db, article.page_id)
