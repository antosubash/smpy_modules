"""The article body: reading one for the canvas, autosaving it, and its history.

Separate from :mod:`news.endpoints.api.articles` because these are the writes
that happen on a timer rather than on a person pressing something. An autosave
must not be able to reach the slug, the status or anything a rename would owe a
redirect for, and the cleanest way to guarantee that is a DTO and a route that
simply cannot carry those fields.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news.content import ArticlesService
from news.contracts.schemas import ArticleBodyUpdate, ArticleDetail, RevisionRead
from news.endpoints.api._deps import detail_of, read_one, require_edit

router = APIRouter(dependencies=[require_edit])
"""``news.edit`` on every route here.

Including the reads: a draft body is unpublished work, and the public site has
its own viewer for the published snapshot.
"""


@router.get("/articles/{article_id}/detail", response_model=ArticleDetail)
async def get_article_detail(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleDetail:
    """Everything the editor screens need, in one request.

    The listing shape widened rather than replaced — see ``detail_of`` — so the
    metadata panel and the canvas read the same title and URL as the list does.
    """
    article = await ArticlesService(db).get_article(article_id)
    return detail_of(article, await read_one(db, article_id))


@router.put("/articles/{article_id}/body", response_model=ArticleDetail)
async def save_article_body(
    article_id: int, body: ArticleBodyUpdate, db: AsyncSession = Depends(get_db)
) -> ArticleDetail:
    """Autosave the block document into the draft.

    The published snapshot is untouched: an author editing a live article is not
    republishing it, and every keystroke reaching readers is the behaviour the
    draft/published split exists to prevent.
    """
    service_ = ArticlesService(db)
    article = await service_.save_body(article_id, body.draft_data)
    return detail_of(article, await read_one(db, article_id))


@router.get("/articles/{article_id}/revisions", response_model=list[RevisionRead])
async def list_article_revisions(
    article_id: int, db: AsyncSession = Depends(get_db)
) -> list[RevisionRead]:
    """The article's history, newest first.

    Every status transition writes one, so this is the audit log rather than
    something kept beside it.
    """
    service_ = ArticlesService(db)
    # Resolved first so a bad id is a 404 rather than an empty list, which
    # would read as "this article has no history".
    await service_.get_article(article_id)
    return [
        RevisionRead(
            id=revision.id or 0,
            article_id=revision.article_id,
            title=revision.title,
            event=revision.event,
            note=revision.note,
            created_at=revision.created_at,
            created_by=revision.created_by,
        )
        for revision in await service_.list_revisions(article_id)
    ]


@router.post(
    "/articles/{article_id}/revisions/{revision_id}/restore",
    response_model=ArticleDetail,
)
async def restore_article_revision(
    article_id: int, revision_id: int, db: AsyncSession = Depends(get_db)
) -> ArticleDetail:
    """Copy a revision back into the draft.

    Deliberately does not publish — see ``RevisionsMixin.restore_revision``.
    """
    article = await ArticlesService(db).restore_revision(article_id, revision_id)
    return detail_of(article, await read_one(db, article_id))
