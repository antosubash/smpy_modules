"""Status transitions — publish, unpublish, review, and the trash.

Their own module because they are the routes with their own authority.
Publishing used to mean publishing a pagebuilder *page*, so it went through that
module's editor→publisher separation; owning the content means owning the
separation, and ``news.publish`` is where it now lives.

``news.edit`` is not enough for any of these. An author who can write an article
should not thereby be able to put it in front of readers on a site that wanted a
review step.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import tag_service
from news.content import ArticlesService
from news.contracts.schemas import ArticleRead, RejectRequest
from news.endpoints.api._deps import read_one, require_edit, require_publish

router = APIRouter()


@router.post(
    "/articles/{article_id}/publish",
    response_model=ArticleRead,
    dependencies=[require_edit, require_publish],
)
async def publish_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Snapshot the draft and serve it."""
    await ArticlesService(db).publish(article_id)
    return await read_one(db, article_id)


@router.post(
    "/articles/{article_id}/unpublish",
    response_model=ArticleRead,
    dependencies=[require_edit, require_publish],
)
async def unpublish_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Take the article off the public site, keeping the draft."""
    await ArticlesService(db).unpublish(article_id)
    return await read_one(db, article_id)


@router.post(
    "/articles/{article_id}/submit",
    response_model=ArticleRead,
    dependencies=[require_edit],
)
async def submit_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Hand a draft to a reviewer.

    ``news.edit`` alone, deliberately: submitting is what an author does when
    they *cannot* publish, so gating it on ``news.publish`` would close the only
    door the separation leaves them.
    """
    await ArticlesService(db).submit_for_review(article_id)
    return await read_one(db, article_id)


@router.post(
    "/articles/{article_id}/approve",
    response_model=ArticleRead,
    dependencies=[require_edit, require_publish],
)
async def approve_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Approve and publish in one action — see ``WorkflowMixin.approve``."""
    await ArticlesService(db).approve(article_id)
    return await read_one(db, article_id)


@router.post(
    "/articles/{article_id}/reject",
    response_model=ArticleRead,
    dependencies=[require_edit, require_publish],
)
async def reject_article(
    article_id: int,
    body: RejectRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ArticleRead:
    """Send a submission back to draft, with a reason the author will see."""
    await ArticlesService(db).reject(article_id, body.note if body else None)
    return await read_one(db, article_id)


@router.post(
    "/articles/{article_id}/trash",
    status_code=204,
    dependencies=[require_edit],
)
async def trash_article(article_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Move the article to the trash. Recoverable; the slug stays claimed.

    Answers 204 rather than the trashed row, and that is forced rather than
    stylistic: every read path filters ``NOT_TRASHED``, so reading the article
    back through the listing query — which is what gives every other route here
    one response shape — finds nothing and 404s, rolling back the very write it
    was reporting on. There is no article to return; that is the point of the
    call.
    """
    await ArticlesService(db).trash(article_id)


@router.post(
    "/articles/{article_id}/restore",
    response_model=ArticleRead,
    dependencies=[require_edit],
)
async def restore_article(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleRead:
    """Bring an article back out of the trash, status untouched."""
    await ArticlesService(db).restore(article_id)
    return await read_one(db, article_id)


@router.delete(
    "/articles/{article_id}/purge",
    status_code=204,
    dependencies=[require_edit, require_publish],
)
async def purge_article(article_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Remove a trashed article for good, with its redirects and tag links.

    Gated on ``news.publish`` as well as ``news.edit``: this is the one action
    in the module that cannot be undone.
    """
    await tag_service.unlink_article(db, article_id)
    await ArticlesService(db).purge(article_id)
