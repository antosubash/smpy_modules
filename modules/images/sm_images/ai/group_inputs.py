"""What a group run consolidates (split from :mod:`.group_run`): the
members' image-scope results (stored ones reused, the rest run through
:mod:`.group_members`) and their display-copy pictures."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from sm_images.ai import group_members
from sm_images.ai.reads import PromptResultRead

__all__ = ["MAX_SIDE", "instruction", "member_results", "needed", "pictures"]

MAX_SIDE = 1024


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
    from sm_images.ai.runner import prepare_image

    store = runtime.store()
    gate = asyncio.Semaphore(group_members.MEMBER_CONCURRENCY)

    async def one(image_id: uuid.UUID) -> bytes:
        async with gate:
            data = await store.read(job.display_keys[image_id])
            return await asyncio.to_thread(prepare_image, data, MAX_SIDE)

    return list(await asyncio.gather(*(one(m.image_id) for m in job.group.members)))


def instruction(job: Any, reads: list[PromptResultRead]) -> str:
    if not reads:
        return job.instruction
    lines = [
        f"- {r.role or r.image_id}: "
        + json.dumps(r.result_data if r.result_data else {"text": r.result_text})
        for r in reads
    ]
    return job.instruction + "\n\nPer-image results:\n" + "\n".join(lines)
