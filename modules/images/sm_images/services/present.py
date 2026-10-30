"""Images as the console shows them: the row plus the URLs that fetch its bytes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_images import access
from sm_images.core import constants
from sm_images.models import Collection, Group, Image, Prompt, Rendition, StepRun
from sm_images.schemas.image import ImageOut, StepRunOut
from sm_images.serving import urls

__all__ = ["present", "present_detail", "present_one", "prompt_names"]


async def present(db: Any, collection: Collection, images: Sequence[Image]) -> list[ImageOut]:
    """One query for the page's ``small`` renditions. A rendition cut from an
    older display copy is not offered: the route would 404 it."""
    if not images:
        return []
    stmt = select(Rendition).where(
        Rendition.image_id.in_([i.id for i in images]), Rendition.size == constants.THUMB_SIZE
    )
    cuts = {r.image_id: r for r in (await db.execute(stmt)).scalars()}
    out = []
    for image in images:
        cut = cuts.get(image.id)
        current = cut is not None and cut.source_generation == image.display_generation
        thumb = urls.rendition_url(image, cut, collection=collection) if current else None
        out.append(
            ImageOut.from_row(
                image,
                thumb_url=thumb,
                display_url=urls.display_url(image, collection=collection),
            )
        )
    return out


async def present_one(db: Any, collection: Collection, image: Image) -> ImageOut:
    return (await present(db, collection, [image]))[0]


async def present_detail(
    db: Any, collection: Collection, image: Image, who: ResourcePrincipal
) -> ImageOut:
    """``present_one`` plus the image's step runs, for the viewer's result views.

    Output (region coordinates, extracted text) and error messages (internals)
    are for those who can edit the collection; a viewer gets the step, its
    status and its error code only - and a prompt step's answer once the
    picture may be shown (``services.prompt_answers``)."""
    out = await present_one(db, collection, image)
    detailed = await access.can_edit(db, who, collection)
    stmt = select(StepRun).where(StepRun.image_id == image.id).order_by(StepRun.step)
    if image.group_id is not None:
        key = select(Group.key).where(
            Group.id == image.group_id, Group.collection_id == collection.id
        )
        out.group_key = (await db.execute(key)).scalar_one_or_none()
    rows = list((await db.execute(stmt)).scalars())
    names = await prompt_names(db, collection, [r.step for r in rows])
    from sm_images.services.prompt_answers import answers

    said = await answers(db, collection, image, editor=detailed)
    out.step_runs = [
        StepRunOut(
            step=r.step,
            label=names.get(r.step),
            answer=said.get(r.step),
            status=r.status.value,
            error_code=r.error_code,
            step_version=r.step_version if detailed else None,
            error_message=r.error_message if detailed else None,
            finished_at=r.finished_at if detailed else None,
            output=r.output if detailed else None,
            output_visible=detailed,
        )
        for r in rows
    ]
    return out


async def prompt_names(db: Any, collection: Collection, steps: list[str]) -> dict[str, str]:
    """``{"prompt:<id>": name}`` for the collection's prompts among ``steps``."""
    from sm_images.ai.prompt_steps import prompt_id_of

    ids: dict[uuid.UUID, str] = {}
    for step in steps:
        pid = prompt_id_of(step)
        if pid is not None:
            ids[pid] = step
    if not ids:
        return {}
    stmt = select(Prompt.id, Prompt.name).where(
        Prompt.id.in_(list(ids)), Prompt.collection_id == collection.id
    )
    return {ids[pid]: name for pid, name in (await db.execute(stmt)).all()}
