"""The members' image-scope results a group run consolidates (``inputs``
``results``/``both``).

A member whose stored result is usable - ``completed``, with content, made
under the member prompt's current revision - is reused. Each other member's
``prompt:<member>`` run is requested and claimed under the image lock (the
lock order every planner follows) and executed here, through the pipeline
executor, at most :data:`MEMBER_CONCURRENCY` at a time. So a member call has
exactly an image prompt run's guarantees: the claim, the once-per-lease
provider call, its own metering key, ``max_retries=0`` and the display gate.
A member someone else is already running is not waited for: it is missing
from this consolidation, and the next group run picks its result up.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.ai.prompt_steps import step_id
from sm_images.models import PromptResult
from sm_images.models.enums import StepStatus
from sm_images.pipeline.claim import claim, insert_missing, load_runs, lock_image
from sm_images.pipeline.cycle import reset_runs

__all__ = ["MEMBER_CONCURRENCY", "MemberResult", "fetch", "run_member", "run_members", "usable"]

MEMBER_CONCURRENCY = 4
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemberResult:
    """The columns of a member's result a group run reads (no ORM object)."""

    image_id: uuid.UUID
    status: StepStatus
    result_data: dict[str, Any] | None
    result_text: str | None
    model_name: str | None
    prompt_revision: int | None


def usable(row: MemberResult | None, revision: int) -> bool:
    return (
        row is not None
        and row.status is StepStatus.COMPLETED
        and row.prompt_revision == revision
        and bool(row.result_data or row.result_text)
    )


async def fetch(
    runtime: Any, tenant: str, prompt_id: uuid.UUID, image_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MemberResult]:
    """The member prompt's results for ``image_ids``, in one query."""
    if not image_ids:
        return {}
    stmt = select(
        PromptResult.image_id,
        PromptResult.status,
        PromptResult.result_data,
        PromptResult.result_text,
        PromptResult.model_name,
        PromptResult.prompt_revision,
    ).where(
        PromptResult.tenant_id == tenant,
        PromptResult.prompt_id == prompt_id,
        PromptResult.image_id.in_(list(image_ids)),
    )
    async with runtime.session_factory() as db:
        rows = [MemberResult(*r) for r in (await db.execute(stmt)).all()]
        await finalize_session(db)
    return {r.image_id: r for r in rows}


async def run_member(runtime: Any, tenant: str, image_id: uuid.UUID, sid: str) -> bool:
    """Request, claim and execute one member's run; ``False`` when someone else
    holds it (or the image is gone)."""
    from sm_images.pipeline.executor import run_step_async

    lease_s = runtime.settings().step_lease_seconds
    claims: list[Any] = []
    async with runtime.session_factory() as db:
        if await lock_image(db, tenant, image_id) is not None:
            now = datetime.now(UTC)
            run = (await load_runs(db, tenant, image_id)).get(sid)
            if run is None:
                await insert_missing(db, image_id, [sid])
            elif run.status is not StepStatus.PENDING:
                await reset_runs(db, tenant, image_id, [sid], now)  # never a live lease
            claims = await claim(db, tenant, image_id, [sid], now, lease_s)
        await finalize_session(db)
    for c in claims:
        await run_step_async(runtime, tenant, image_id, c.step, c.token)
    return bool(claims)


async def run_members(
    runtime: Any, tenant: str, prompt_id: uuid.UUID, image_ids: Sequence[uuid.UUID]
) -> None:
    """Run the member prompt on ``image_ids``, at most :data:`MEMBER_CONCURRENCY` at once."""
    sid = step_id(prompt_id)
    gate = asyncio.Semaphore(MEMBER_CONCURRENCY)

    async def one(image_id: uuid.UUID) -> None:
        async with gate:
            await run_member(runtime, tenant, image_id, sid)

    # A member that raised is simply missing; the others still finish.
    done = await asyncio.gather(*(one(i) for i in image_ids), return_exceptions=True)
    from celery.exceptions import SoftTimeLimitExceeded

    for image_id, outcome in zip(image_ids, done, strict=True):
        if isinstance(outcome, BaseException):
            if isinstance(outcome, SoftTimeLimitExceeded) or not isinstance(outcome, Exception):
                raise outcome  # the task's time is up (or it is being cancelled)
            logger.warning("images.group.member_failed image=%s", image_id, exc_info=outcome)
