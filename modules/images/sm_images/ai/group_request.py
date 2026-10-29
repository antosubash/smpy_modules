"""``POST /prompts/{id}/run`` for a group-scope prompt: request, then dispatch.

Per group, one short transaction under the group lock marks the run requested
(:func:`~sm_images.ai.group_lease.request`: ``missing`` - no completed result;
``stale`` - those and results of an older revision; ``all`` - every group
again; never one already in flight). After it commits the run is dispatched:
inline on an eager runtime, otherwise ``images.run_group_prompt`` on the
``images_heavy`` queue, stamped with the tenant. A whole collection is walked
in keyset chunks of :data:`CHUNK` groups (by ``images.run_prompt`` on a broker).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select

from sm_images.ai import group_lease
from sm_images.models import Group, Prompt
from sm_images.models.enums import PromptScope

__all__ = ["CHUNK", "GROUP_QUEUE", "dispatch_group", "request_groups"]

CHUNK = 500
GROUP_QUEUE = "images_heavy"


async def _groups(
    runtime: Any, tenant: str, collection_id: uuid.UUID, only: Sequence[uuid.UUID] | None
) -> AsyncIterator[uuid.UUID]:
    after: uuid.UUID | None = None
    while True:
        stmt = (
            select(Group.id)
            .where(Group.collection_id == collection_id, Group.tenant_id == tenant)
            .order_by(Group.id)
            .limit(CHUNK)
        )
        if only is not None:
            stmt = stmt.where(Group.id.in_(list(only)))
        if after is not None:
            stmt = stmt.where(Group.id > after)
        async with runtime.session_factory() as db:
            ids = list((await db.execute(stmt)).scalars())
            await finalize_session(db)
        for group_id in ids:
            yield group_id
        if len(ids) < CHUNK:
            return
        after = ids[-1]


async def dispatch_group(
    runtime: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID
) -> None:
    if runtime.is_eager():
        from sm_images.ai.group_run import run_group

        await run_group(runtime, tenant, prompt_id, group_id)
        return
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.tasks import run_group_prompt_task

    run_group_prompt_task.s(str(prompt_id), str(group_id)).apply_async(
        queue=GROUP_QUEUE, headers={TENANT_HEADER: tenant}
    )


async def request_groups(
    runtime: Any,
    tenant: str,
    prompt_id: uuid.UUID,
    scope: str,
    group_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Request and dispatch; returns how many groups got a new run."""
    lease_s = runtime.settings().step_lease_seconds
    with tenant_context(tenant):
        stmt = select(Prompt.collection_id, Prompt.revision).where(
            Prompt.id == prompt_id, Prompt.tenant_id == tenant, Prompt.scope == PromptScope.GROUP
        )
        async with runtime.session_factory() as db:
            found = (await db.execute(stmt)).first()
            await finalize_session(db)
        if found is None:
            return 0
        count = 0
        async for group_id in _groups(runtime, tenant, found.collection_id, group_ids):
            async with runtime.session_factory() as db:
                now = datetime.now(UTC)
                changed = await group_lease.request(
                    db, tenant, prompt_id, group_id, scope, found.revision, now, lease_s
                )
                await finalize_session(db)
            if changed:
                count += 1
                await dispatch_group(runtime, tenant, prompt_id, group_id)
        return count
