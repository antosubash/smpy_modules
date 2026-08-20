"""Tag endpoints. Same ``/taxonomy`` prefix, and the same reason for it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import tag_service
from news.contracts.schemas import (
    TagCreate,
    TagListResponse,
    TagMerge,
    TagMergeResult,
    TagRead,
    TagUpdate,
)
from news.endpoints.api._deps import require_edit

router = APIRouter(prefix="/taxonomy", dependencies=[require_edit])


async def _load(db: AsyncSession, tag_id: int):
    tag = await tag_service.get(db, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    return tag


def _read(tag, count: int) -> TagRead:
    return TagRead(id=tag.id or 0, name=tag.name, slug=tag.slug, article_count=count)


@router.get("/tags", response_model=TagListResponse)
async def list_tags(db: AsyncSession = Depends(get_db)) -> TagListResponse:
    return TagListResponse(items=await tag_service.list_tags(db))


@router.post("/tags", response_model=TagRead, status_code=201)
async def create_tag(body: TagCreate, db: AsyncSession = Depends(get_db)) -> TagRead:
    """Find-or-create, so the screen's one input cannot make a duplicate.

    201 either way: the caller wanted the tag to exist and now it does, and
    distinguishing the two would only invite the client to branch on it.
    """
    tag = await tag_service.get_or_create(db, body.name)
    return _read(tag, 0)


@router.put("/tags/{tag_id}", response_model=TagRead)
async def rename_tag(
    tag_id: int, body: TagUpdate, db: AsyncSession = Depends(get_db)
) -> TagRead:
    tag = await _load(db, tag_id)
    updated = await tag_service.rename(db, tag, body.name)
    counts = {t.id: t.article_count for t in await tag_service.list_tags(db)}
    return _read(updated, counts.get(updated.id or 0, 0))


@router.post("/tags/{tag_id}/merge", response_model=TagMergeResult)
async def merge_tag(
    tag_id: int, body: TagMerge, db: AsyncSession = Depends(get_db)
) -> TagMergeResult:
    """Fold ``source_id`` into ``tag_id``; the source row is removed."""
    target = await _load(db, tag_id)
    source = await _load(db, body.source_id)
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="Cannot merge a tag into itself.")
    return TagMergeResult(moved=await tag_service.merge(db, source=source, target=target))


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Remove the tag. Its links go with it; the articles do not."""
    tag = await _load(db, tag_id)
    await tag_service.delete(db, tag)
