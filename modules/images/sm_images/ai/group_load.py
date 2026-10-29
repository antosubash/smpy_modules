"""A group run's load phase: one short read session, closed before any work.

Reads the group prompt at its stored revision, the group and its untrashed
members in the collection's role order (at most :data:`MAX_MEMBERS` + 1, so
an oversized group is refused rather than truncated), whether each member's
display copy may leave the system (the test serving and the image steps use),
and - for ``inputs`` ``results``/``both`` - the member prompt's revision.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images import redaction
from sm_images.ai.reads import GroupMemberRead, GroupRead
from sm_images.models import Collection, Group, Image, Prompt
from sm_images.models.enums import PromptScope
from sm_images.services.groups import member_order

__all__ = ["MAX_MEMBERS", "GroupJob", "MemberPrompt", "display_now", "load"]

MAX_MEMBERS = 50
"""Most members one consolidation is made over; a bigger group fails ``group_too_large``."""


@dataclass(frozen=True)
class MemberPrompt:
    id: uuid.UUID
    revision: int


@dataclass(frozen=True)
class GroupJob:
    tenant: str
    prompt_id: uuid.UUID
    revision: int
    instruction: str
    output_schema: dict[str, Any] | None
    inputs: str
    preset_id: str | None
    member: MemberPrompt | None
    group: GroupRead
    too_many: bool
    display_keys: dict[uuid.UUID, str] = field(default_factory=dict)
    """Each member's display copy (the original when it is its own display copy)."""
    unsafe: tuple[uuid.UUID, ...] = ()
    """Members whose display copy may not leave the system yet."""


async def _safe(db: Any, collection: Collection, image: Image) -> bool:
    if redaction.trusts_display(collection, image):
        return True
    return not await redaction.pending(db, collection, image)


async def _member_prompt(db: Any, tenant: str, prompt: Prompt) -> MemberPrompt | None:
    if prompt.member_prompt_id is None:
        return None
    stmt = select(Prompt.id, Prompt.revision).where(
        Prompt.id == prompt.member_prompt_id,
        Prompt.tenant_id == tenant,
        Prompt.collection_id == prompt.collection_id,
        Prompt.scope == PromptScope.IMAGE,
    )
    row = (await db.execute(stmt)).first()
    return None if row is None else MemberPrompt(*row)


async def _read(db: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID) -> Any:
    prompt = (
        await db.execute(
            select(Prompt).where(
                Prompt.id == prompt_id,
                Prompt.tenant_id == tenant,
                Prompt.scope == PromptScope.GROUP,
            )
        )
    ).scalar_one_or_none()
    if prompt is None:
        return None
    group = (
        await db.execute(
            select(Group).where(
                Group.id == group_id,
                Group.tenant_id == tenant,
                Group.collection_id == prompt.collection_id,
            )
        )
    ).scalar_one_or_none()
    collection = (
        await db.execute(
            select(Collection).where(
                Collection.id == prompt.collection_id, Collection.tenant_id == tenant
            )
        )
    ).scalar_one_or_none()
    if group is None or collection is None:
        return None
    stmt = (
        select(Image)
        .where(Image.group_id == group_id, Image.tenant_id == tenant, Image.is_deleted.is_(False))
        .order_by(*member_order(list(collection.group_roles or [])))
        .limit(MAX_MEMBERS + 1)
    )
    images = list((await db.execute(stmt)).scalars())
    return prompt, group, collection, images


async def load(
    runtime: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID
) -> GroupJob | None:
    """The job, or ``None`` when the prompt (as a group prompt) or the group is gone."""
    async with runtime.session_factory() as db:
        found = await _read(db, tenant, prompt_id, group_id)
        job = None
        if found is not None:
            prompt, group, collection, images = found
            kept = images[:MAX_MEMBERS]
            unsafe = tuple([i.id for i in kept if not await _safe(db, collection, i)])
            job = GroupJob(
                tenant=tenant,
                prompt_id=prompt.id,
                revision=prompt.revision,
                instruction=prompt.instruction,
                output_schema=prompt.output_schema,
                inputs=prompt.inputs or "images",
                preset_id=prompt.preset_id,
                member=await _member_prompt(db, tenant, prompt),
                group=GroupRead(
                    id=group.id,
                    collection_id=group.collection_id,
                    key=group.key,
                    name=group.name,
                    members=tuple(
                        GroupMemberRead(image_id=i.id, role=i.group_role, filename=i.filename)
                        for i in kept
                    ),
                ),
                too_many=len(images) > MAX_MEMBERS,
                display_keys={i.id: i.display_key or i.storage_key for i in kept},
                unsafe=unsafe,
            )
        await finalize_session(db)  # read-only: closes the transaction before any work
    return job


async def display_now(
    runtime: Any, tenant: str, group_id: uuid.UUID, image_id: uuid.UUID
) -> tuple[str, bool] | None:
    """A member's display copy re-read mid-run (the one loaded was replaced):
    ``(key, safe)``, or ``None`` once it is no longer an untrashed member."""
    async with runtime.session_factory() as db:
        stmt = select(Image, Collection).join(Collection, Collection.id == Image.collection_id)
        found = (
            await db.execute(
                stmt.where(
                    Image.id == image_id,
                    Image.group_id == group_id,
                    Image.tenant_id == tenant,
                    Image.is_deleted.is_(False),
                )
            )
        ).first()
        now = None
        if found is not None:
            image, collection = found
            now = (image.display_key or image.storage_key, await _safe(db, collection, image))
        await finalize_session(db)
    return now
