"""What a group run consolidates (split from :mod:`.group_run`): the
members' image-scope results (stored ones reused, the rest run through
:mod:`.group_members`) and their display-copy pictures.

The display keys are the load's: a copy replaced since (a re-run redaction)
is gone from storage, so a missing object is re-resolved once
(:func:`.group_load.display_now`). A member no longer in the group is left
out, as the load would have; one whose current copy may not leave yet is
:class:`DisplayNotReady`, the load gate's ``display_not_ready``."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from file_storage.contracts.service import StorageNotFoundError

from sm_images.pipeline.ai import group_load, group_members
from sm_images.pipeline.ai.reads import PromptResultRead

__all__ = ["MAX_SIDE", "DisplayNotReady", "instruction", "member_results", "needed", "pictures"]

MAX_SIDE = 1024


class DisplayNotReady(Exception):  # noqa: N818 - reads as the condition
    """A member's replaced display copy may not leave the system yet."""


async def needed(runtime: Any, job: Any) -> tuple[dict[uuid.UUID, Any], list[uuid.UUID]]:
    """The members' stored results, and the members that need a call."""
    ids = [m.image_id for m in job.group.members]
    found = await group_members.fetch(runtime, job.tenant, job.member.id, ids)
    need = [i for i in ids if not group_members.usable(found.get(i), job.member.revision)]
    return found, need


async def member_results(
    runtime: Any, job: Any, found: dict[uuid.UUID, Any], need: list[uuid.UUID]
) -> tuple[list[PromptResultRead], list[str]]:
    members = job.group.members
    if need:
        m = job.member
        await group_members.run_members(runtime, job.tenant, m.id, m.revision, need)
        ids = [x.image_id for x in members]
        found = await group_members.fetch(runtime, job.tenant, m.id, ids)
    reads, missing = [], []
    for m in members:
        row = found.get(m.image_id)
        if not group_members.usable(row, job.member.revision):
            missing.append(m.role or str(m.image_id))
            continue
        reads.append(
            PromptResultRead(
                prompt_id=job.member.id,
                image_id=m.image_id,
                role=m.role,
                result_data=row.result_data,
                result_text=row.result_text,
                model_name=row.model_name,
                prompt_revision=row.prompt_revision,
            )
        )
    return reads, missing


async def pictures(runtime: Any, job: Any) -> list[bytes]:
    from sm_images.pipeline.ai.runner import prepare_image

    store = runtime.store()
    gate = asyncio.Semaphore(group_members.MEMBER_CONCURRENCY)

    async def read(image_id: uuid.UUID) -> bytes | None:
        try:
            return await store.read(job.display_keys[image_id])
        except StorageNotFoundError:
            now = await group_load.display_now(runtime, job.tenant, job.group.id, image_id)
        if now is None:
            return None
        if not now[1]:
            raise DisplayNotReady(str(image_id))
        return await store.read(now[0])

    async def one(image_id: uuid.UUID) -> bytes | None:
        async with gate:
            data = await read(image_id)
            return None if data is None else await asyncio.to_thread(prepare_image, data, MAX_SIDE)

    found = await asyncio.gather(*(one(m.image_id) for m in job.group.members))
    return [p for p in found if p is not None]


def instruction(job: Any, reads: list[PromptResultRead]) -> str:
    if not reads:
        return job.instruction
    lines = [
        f"- {r.role or r.image_id}: "
        + json.dumps(r.result_data if r.result_data else {"text": r.result_text})
        for r in reads
    ]
    return job.instruction + "\n\nPer-image results:\n" + "\n".join(lines)
