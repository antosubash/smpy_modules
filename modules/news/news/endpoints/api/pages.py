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
from news.contracts.schemas import ArticleRead, ArticleWithPageCreate
from news.endpoints.api._deps import read_one_by_page, require_edit
from news.integrations.pagebuilder import (
    create_article_page,
    publish_page,
    require_page_edit,
    require_page_publish,
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
    page = await create_article_page(db, title=body.title.strip(), slug=body.slug)
    await service.create(
        db,
        page_id=page.id or 0,
        category=body.category,
        published_at=body.published_at,
        author=body.author,
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
