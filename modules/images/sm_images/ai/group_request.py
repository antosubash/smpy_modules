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

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import and_, func, or_, select

from sm_images.ai import group_lease
from sm_images.ai.run import _ids
from sm_images.models import Collection, Group, Prompt, PromptResult
from sm_images.models.enums import PromptScope, StepStatus
from sm_images.pipeline.runtime import first_row

__all__ = ["CHUNK", "GROUP_QUEUE", "dispatch_group", "recover_group_runs", "request_groups"]

logger = logging.getLogger(__name__)

CHUNK = 500
GROUP_QUEUE = "images_heavy"


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
    *,
    allowed: Callable[[], Awaitable[bool]] | None = None,
) -> int:
    """Request and dispatch; returns how many groups got a new run.

    ``allowed``: the starter's right (``sm_images.access.starter_right``), asked
    before each chunk of :data:`CHUNK` groups after the first (the caller
    asked before the first); ``False`` stops the run where it is."""
    lease_s = runtime.settings().step_lease_seconds
    with tenant_context(tenant):
        stmt = select(Prompt.collection_id, Prompt.revision).where(
            Prompt.id == prompt_id, Prompt.tenant_id == tenant, Prompt.scope == PromptScope.GROUP
        )
        found = await first_row(runtime, stmt)
        if found is None:
            return 0
        count = seen = 0
        async for group_id in _ids(
            runtime, Group, tenant, found.collection_id, group_ids, chunk=CHUNK
        ):
            seen += 1
            if allowed is not None and seen > 1 and (seen - 1) % CHUNK == 0 and not await allowed():
                logger.info("images.prompt_run.access_revoked prompt=%s", prompt_id)
                return count
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


def _lost(tenant: str, now: datetime, cutoff: datetime) -> Any:
    """Group runs of live collections that nobody is carrying: requested
    longer than ``cutoff`` ago and never claimed (a lost dispatch), or claimed
    under a lease that has expired (a dead worker)."""
    return (
        select(PromptResult.id, PromptResult.prompt_id, PromptResult.group_id)
        .join(Group, Group.id == PromptResult.group_id)
        .join(Collection, Collection.id == Group.collection_id)
        .where(
            PromptResult.tenant_id == tenant,
            PromptResult.group_id.is_not(None),
            Collection.is_deleted.is_(False),
            or_(
                and_(
                    PromptResult.status == StepStatus.PENDING,
                    # by the request alone: a later write (audit, a refused
                    # re-request) must not push recovery back
                    func.coalesce(PromptResult.requested_at, PromptResult.created_at) < cutoff,
                ),
                and_(
                    PromptResult.status == StepStatus.RUNNING,
                    PromptResult.lease_expires_at < now,
                ),
            ),
        )
        .order_by(PromptResult.id)
        .limit(CHUNK)
    )


async def recover_group_runs(runtime: Any, tenant: str, now: datetime, cutoff: datetime) -> int:
    """Dispatch every lost group run again (``images.reconcile``), in pages.
    The claim is fenced, so a run that is in fact still on its way is not
    executed twice. The caller has bound ``tenant``."""
    found: list[tuple[uuid.UUID, uuid.UUID]] = []
    after = None
    while True:
        stmt = _lost(tenant, now, cutoff)
        if after is not None:
            stmt = stmt.where(PromptResult.id > after)
        async with runtime.session_factory() as db:
            rows = list((await db.execute(stmt)).all())
            await finalize_session(db)
        found += [(prompt_id, group_id) for _, prompt_id, group_id in rows]
        if len(rows) < CHUNK:
            break
        after = rows[-1][0]
    for prompt_id, group_id in found:
        await dispatch_group(runtime, tenant, prompt_id, group_id)
    return len(found)
