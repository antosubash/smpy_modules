"""``POST /prompts/{id}/run``: request a prompt's run on images, then plan them.

A group-scope prompt is handed to :mod:`sm_images.ai.group_request` instead.

Per image, one short transaction under the image lock (the lock order every
inserter and reset follows): a run with none yet gets a pending row, a final
run the ``scope`` selects goes back to ``pending``, and a pending or live run
is left alone (it is already on its way). The image is then dispatched; the
planner runs the requested prompt step behind the display mutator.

* ``missing`` - images with no completed result;
* ``stale`` - those, and results made under an older prompt revision;
* ``all`` - every image again.

A list of ``image_ids`` (at most :data:`IDS_MAX`) is handled in the request.
A whole collection is walked in keyset chunks: inline when the runtime is
eager, otherwise by ``images.run_prompt`` on the orchestrators' queue.
Nothing here starts a processing cycle: a requested prompt does not make an
image "processed" again.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.ai.prompt_steps import step_id
from sm_images.models import Image, Prompt, StepRun
from sm_images.models.enums import PromptScope, StepStatus
from sm_images.pipeline.claim import insert_missing, load_runs, lock_image
from sm_images.pipeline.cycle import reset_runs
from sm_images.pipeline.orchestrate import submit_dispatch
from sm_images.pipeline.runtime import Runtime
from sm_images.starter_right import holds_right

__all__ = ["CHUNK", "IDS_MAX", "RunScope", "launch", "run_prompt", "wanted"]

logger = logging.getLogger(__name__)

RunScope = Literal["missing", "stale", "all"]
CHUNK = 500
IDS_MAX = 500


def wanted(run: StepRun | None, scope: RunScope, revision: int, now: datetime) -> bool:
    if run is None:
        return True
    if run.status is StepStatus.PENDING:
        return False
    if run.status is StepStatus.RUNNING:
        return run.lease_expires_at is None or run.lease_expires_at < now
    if scope == "all" or run.status is not StepStatus.COMPLETED:
        return True
    return scope == "stale" and run.step_version != revision


async def _request(
    db: Any, tenant: str, image_id: uuid.UUID, sid: str, revision: int, scope: RunScope
) -> bool:
    if await lock_image(db, tenant, image_id) is None:
        return False
    now = datetime.now(UTC)
    run = (await load_runs(db, tenant, image_id)).get(sid)
    if not wanted(run, scope, revision, now):
        return False
    if run is None:
        await insert_missing(db, image_id, [sid])
        return True
    return bool(await reset_runs(db, tenant, image_id, [sid], now))


async def _images(
    runtime: Runtime, tenant: str, collection_id: uuid.UUID, only: Sequence[uuid.UUID] | None
) -> AsyncIterator[uuid.UUID]:
    after: uuid.UUID | None = None
    while True:
        stmt = (
            select(Image.id)
            .where(Image.collection_id == collection_id, Image.tenant_id == tenant)
            .order_by(Image.id)
            .limit(CHUNK)
        )
        if only is not None:
            stmt = stmt.where(Image.id.in_(list(only)))
        if after is not None:
            stmt = stmt.where(Image.id > after)
        async with runtime.session_factory() as db:
            ids = list((await db.execute(stmt)).scalars())
            await finalize_session(db)
        for image_id in ids:
            yield image_id
        if len(ids) < CHUNK:
            return
        after = ids[-1]


async def _prompt(runtime: Runtime, tenant: str, prompt_id: uuid.UUID) -> Any:
    stmt = select(Prompt.collection_id, Prompt.revision, Prompt.scope).where(
        Prompt.id == prompt_id, Prompt.tenant_id == tenant
    )
    async with runtime.session_factory() as db:
        row = (await db.execute(stmt)).first()
        await finalize_session(db)
    return row


async def run_prompt(
    runtime: Runtime,
    tenant: str,
    prompt_id: uuid.UUID,
    scope: RunScope,
    image_ids: Sequence[uuid.UUID] | None = None,
    group_ids: Sequence[uuid.UUID] | None = None,
    *,
    run_as: str | None = None,
    access_basis: str | None = None,
) -> int:
    """Request and dispatch; returns how many images (or groups) got a new run.

    ``run_as``/``access_basis``: the starter of a queued whole-collection run
    (owner or ``images.manage``), re-checked first and before each chunk of
    :data:`CHUNK` images; a lost right stops the run where it is."""
    found = await _prompt(runtime, tenant, prompt_id)
    if found is None:
        return 0

    async def allowed() -> bool:
        return await holds_right(
            runtime, tenant, found.collection_id, run_as, access_basis, shares=False
        )

    if not await allowed():
        logger.info("images.prompt_run.access_revoked prompt=%s", prompt_id)
        return 0
    if found.scope is PromptScope.GROUP:  # per group (``image_ids`` do not apply)
        from sm_images.ai.group_request import request_groups

        return await request_groups(runtime, tenant, prompt_id, scope, group_ids, allowed=allowed)
    sid = step_id(prompt_id)
    count = seen = 0
    async for image_id in _images(runtime, tenant, found.collection_id, image_ids):
        seen += 1
        if seen > 1 and (seen - 1) % CHUNK == 0 and not await allowed():
            logger.info("images.prompt_run.access_revoked prompt=%s", prompt_id)
            return count
        async with runtime.session_factory() as db:
            changed = await _request(db, tenant, image_id, sid, found.revision, scope)
            await finalize_session(db)
        if changed:
            count += 1
            await submit_dispatch(runtime, tenant, image_id)
    return count


async def launch(
    runtime: Runtime,
    tenant: str,
    prompt_id: uuid.UUID,
    scope: RunScope,
    image_ids: Sequence[uuid.UUID] | None,
    group_ids: Sequence[uuid.UUID] | None = None,
    *,
    run_as: str | None = None,
    access_basis: str | None = None,
) -> int | None:
    """Inline for a list or an eager runtime (the count); else queued (``None``),
    carrying the starter so the worker re-checks their right."""
    starter = {"run_as": run_as, "access_basis": access_basis}
    if image_ids is not None or group_ids is not None or runtime.is_eager():
        return await run_prompt(runtime, tenant, prompt_id, scope, image_ids, group_ids, **starter)
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.task_config import QUEUE_IMPORTS
    from sm_images.tasks import run_prompt_task

    run_prompt_task.s(str(prompt_id), scope, **starter).apply_async(
        queue=QUEUE_IMPORTS, headers={TENANT_HEADER: tenant}
    )
    return None
