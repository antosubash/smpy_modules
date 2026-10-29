"""The review queue: completed prompt results of a collection, by id.

Only untrashed images and groups; a stranger never reaches here (the route
loads the collection through the edit policy). Rows are an editor's, so the
output is always shown (``output_visible``).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from sm_images.ai.review import version_of
from sm_images.models import Collection, Group, Image, Prompt, PromptResult
from sm_images.models.enums import ReviewStatus, StepStatus
from sm_images.schemas.review import ReviewItemOut
from sm_images.services import present

__all__ = ["item_out", "page"]


async def item_out(
    db: Any, collection: Collection, row: PromptResult, prompt: Prompt
) -> ReviewItemOut:
    stale = row.prompt_revision is not None and row.prompt_revision != prompt.revision
    extra: dict[str, Any] = {}
    if row.image_id is not None:
        image = (await db.execute(select(Image).where(Image.id == row.image_id))).scalar_one()
        shown = await present.present_one(db, collection, image)
        extra = {"filename": shown.filename, "thumb_url": shown.thumb_url}
    elif row.group_id is not None:
        key = select(Group.key).where(Group.id == row.group_id)
        extra = {"group_key": (await db.execute(key)).scalar_one_or_none()}
    return ReviewItemOut.model_validate(
        {
            **row.model_dump(),
            "history": list(row.history or []),
            "stale": stale,
            "version": version_of(row),
            "prompt_name": prompt.name,
            "output_schema": prompt.output_schema,
            **extra,
        }
    )


async def page(
    db: Any,
    collection: Collection,
    *,
    status: ReviewStatus | None,
    prompt_id: Any,
    limit: int,
    after: int | None,
) -> tuple[list[ReviewItemOut], int | None]:
    stmt = (
        select(PromptResult, Prompt)
        .join(Prompt, Prompt.id == PromptResult.prompt_id)
        .outerjoin(Image, Image.id == PromptResult.image_id)
        .outerjoin(Group, Group.id == PromptResult.group_id)
        .where(
            Prompt.collection_id == collection.id,
            PromptResult.status == StepStatus.COMPLETED,
            (PromptResult.image_id.is_(None)) | (Image.is_deleted.is_(False)),
            (PromptResult.group_id.is_(None)) | (Group.collection_id == collection.id),
        )
        .order_by(PromptResult.id)
        .limit(limit + 1)
    )
    if status is not None:
        stmt = stmt.where(PromptResult.review_status == status)
    if prompt_id is not None:
        stmt = stmt.where(PromptResult.prompt_id == prompt_id)
    if after is not None:
        stmt = stmt.where(PromptResult.id > after)
    found = list((await db.execute(stmt)).all())
    more = len(found) > limit
    found = found[:limit]
    items = [await item_out(db, collection, r, p) for r, p in found]
    return items, (found[-1][0].id if more and found else None)
