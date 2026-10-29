"""Run a group-scope prompt over one group (spec §3 "Group runs").

``run_group`` claims the group's result row (:mod:`.group_lease`) and
:func:`execute` works under that lease, renewed in the background:

1. **load** (:mod:`.group_load`) - the prompt, the members in role order;
2. **gates**, before anything is sent or charged: an empty or oversized group,
   a member whose display copy may not leave yet (``display_not_ready`` - the
   whole run, not that member: a consolidation never silently skips a photo
   for privacy), an unsafe stored schema, an unconfigured model;
3. **members** (``inputs`` ``results``/``both``, :mod:`.group_members`) -
   stored current-revision results reused, the rest run through the executor,
   at most four at a time, each metered as an image prompt run;
4. **pictures** (``images``/``both``) - every member's display copy, never an
   original, prepared like an image prompt's, four at a time, off the loop;
5. nothing usable - ``no_usable_inputs``, uncharged;
6. **the consolidation** - claimed once per lease (``ai_started_at``), metered
   once (``images:{tenant}:group:{group}:prompt:{prompt}:{revision}:{token}``),
   one provider request at temperature 0 with no retries, its output validated
   against the prompt's schema;
7. **the cross-check** - the prompt's preset's hook, pure, with no session open
   (:mod:`.cross_check`), its failure stored as ``{"error"}``;
8. **store** (:mod:`.group_store`), fenced by the lease.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session, tenant_context

from sm_images.ai import group_lease, group_load, group_members, group_store
from sm_images.ai.cross_check import run_cross_check
from sm_images.ai.group_store import GroupOutcome
from sm_images.ai.reads import PromptResultRead
from sm_images.ai.results import PromptWrite, write_size
from sm_images.pipeline import registry
from sm_images.pipeline.claim import LostLease

__all__ = ["SOURCE", "execute", "metering_key", "run_group"]

logger = logging.getLogger(__name__)
SOURCE = "images:group_prompt"
MAX_SIDE = 1024
NEEDS_MEMBERS = ("results", "both")
SENDS_IMAGES = ("images", "both")


def _now() -> datetime:
    return datetime.now(UTC)


def metering_key(tenant: str, job: Any, group_id: uuid.UUID, token: uuid.UUID) -> str:
    return f"images:{tenant}:group:{group_id}:prompt:{job.prompt_id}:{job.revision}:{token}"


class _Lease:
    def __init__(self, runtime: Any, tenant: str, ids: tuple[uuid.UUID, uuid.UUID], token: Any):
        self.runtime, self.tenant, self.ids, self.token = runtime, tenant, ids, token
        self.lease_s = runtime.settings().step_lease_seconds
        self.lost = False

    async def _db(self, fn: Any, *args: Any) -> bool:
        async with self.runtime.session_factory() as db:
            ok = await fn(db, self.tenant, *self.ids, self.token, _now(), *args)
            await finalize_session(db)
        return ok

    async def start_call(self) -> None:
        if not await self._db(group_lease.start_call):
            raise LostLease(f"group {self.ids[1]}: the consolidation call already started")

    async def keep_alive(self) -> None:
        while not self.lost:
            await asyncio.sleep(max(self.lease_s / 3, 1))
            try:
                self.lost = not await self._db(group_lease.renew, self.lease_s)
            except Exception:  # transient: the next round, or the store, decides
                logger.warning("images.group.renew_failed", exc_info=True)


async def _member_results(runtime: Any, job: Any) -> tuple[list[PromptResultRead], list[str]]:
    members = job.group.members
    ids = [m.image_id for m in members]
    found = await group_members.fetch(runtime, job.tenant, job.member.id, ids)
    need = [i for i in ids if not group_members.usable(found.get(i), job.member.revision)]
    if need:
        await group_members.run_members(runtime, job.tenant, job.member.id, need)
        found = await group_members.fetch(runtime, job.tenant, job.member.id, ids)
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


async def _pictures(runtime: Any, job: Any) -> list[bytes]:
    from sm_images.ai.runner import prepare_image

    store = runtime.store()
    gate = asyncio.Semaphore(group_members.MEMBER_CONCURRENCY)

    async def one(image_id: uuid.UUID) -> bytes:
        async with gate:
            data = await store.read(job.display_keys[image_id])
            return await asyncio.to_thread(prepare_image, data, MAX_SIDE)

    return list(await asyncio.gather(*(one(m.image_id) for m in job.group.members)))


def _instruction(job: Any, reads: list[PromptResultRead]) -> str:
    if not reads:
        return job.instruction
    lines = [
        f"- {r.role or r.image_id}: "
        + json.dumps(r.result_data if r.result_data else {"text": r.result_text})
        for r in reads
    ]
    return job.instruction + "\n\nPer-image results:\n" + "\n".join(lines)


def _output_type(job: Any) -> Any:
    from sm_images.ai.schema_safety import output_model

    if job.output_schema is None:
        return str
    return output_model(job.output_schema, key=(job.prompt_id, job.revision))


async def _work(runtime: Any, job: Any, lease: _Lease) -> GroupOutcome:
    from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
    from sm_ai import contracts

    from sm_images.ai.runner import run_structured
    from sm_images.ai.schema_safety import UnsafeSchema

    members = job.group.members
    if not members:
        return GroupOutcome.failed("group_empty", "the group has no images")
    if job.too_many:
        return GroupOutcome.failed("group_too_large", f"over {group_load.MAX_MEMBERS} images")
    if job.unsafe:
        return GroupOutcome.failed("display_not_ready", f"{len(job.unsafe)} not redacted yet")
    try:  # stored before a cap existed, or edited in the database: refused here too
        out_type = _output_type(job)
    except UnsafeSchema as exc:
        return GroupOutcome.failed("unsafe_output_schema", exc)
    try:
        model = contracts.resolve_model(max_retries=0)  # no SDK retries: one charge, one request
    except contracts.AiError as exc:
        return GroupOutcome.failed("ai_not_configured", exc)
    reads: list[PromptResultRead] = []
    missing: list[str] = []
    if job.inputs in NEEDS_MEMBERS:
        if job.member is None:
            return GroupOutcome.failed("member_prompt_missing", "no image prompt to consolidate")
        reads, missing = await _member_results(runtime, job)
    pictures = await _pictures(runtime, job) if job.inputs in SENDS_IMAGES else []
    if not reads and not pictures:
        return GroupOutcome.failed("no_usable_inputs", f"missing: {', '.join(missing)}")
    await lease.start_call()
    admitted = await contracts.consume_requests(
        job.tenant,
        idempotency_key=metering_key(job.tenant, job, job.group.id, lease.token),
        source=SOURCE,
        session_factory=runtime.session_factory,
    )
    if not admitted:
        return GroupOutcome.failed("quota_exceeded", "the plan's AI request limit is used up")
    try:
        data, model_name = await run_structured(
            _instruction(job, reads), out_type, pictures, model=model, temperature=0.0
        )
    except UnexpectedModelBehavior as exc:
        return GroupOutcome.failed("invalid_output", exc)
    except ModelAPIError as exc:
        return GroupOutcome.failed("ai_error", exc)
    write = PromptWrite(
        prompt_id=job.prompt_id,
        revision=job.revision,
        data=data if isinstance(data, dict) else None,
        text=data if isinstance(data, str) else None,
        model_name=model_name,
    )
    limit = runtime.settings().step_output_max_bytes
    if (size := write_size(write)) > limit:
        return GroupOutcome.failed("output_too_large", f"{size} bytes; the limit is {limit}")
    summary = PromptResultRead(
        prompt_id=job.prompt_id,
        group_id=job.group.id,
        result_data=write.data,
        result_text=write.text,
        model_name=model_name,
        prompt_revision=job.revision,
    )
    preset = registry.get_preset(job.preset_id) if job.preset_id else None
    hook = getattr(preset, "cross_check", None)
    checked = run_cross_check(hook, job.group, [*reads, summary], limit)
    if missing:
        return GroupOutcome(write, checked, "member_results_missing", ", ".join(missing))
    return GroupOutcome(write, checked)


async def execute(
    runtime: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID, token: uuid.UUID
) -> bool:
    """Work under the claimed lease ``token`` and store; ``True`` when recorded."""
    from celery.exceptions import SoftTimeLimitExceeded

    with tenant_context(tenant):
        lease = _Lease(runtime, tenant, (prompt_id, group_id), token)
        keeper = asyncio.ensure_future(lease.keep_alive())
        try:
            job = await group_load.load(runtime, tenant, prompt_id, group_id)
            if job is None:  # the prompt or the group is gone, and its result with it
                return False
            outcome = await _work(runtime, job, lease)
        except LostLease:
            return False
        except SoftTimeLimitExceeded as exc:
            failed = GroupOutcome.failed("time_limit", exc)
            await group_store.finish(runtime, tenant, prompt_id, group_id, token, failed)
            raise
        except Exception as exc:
            logger.exception("images.group.internal_error prompt=%s group=%s", prompt_id, group_id)
            outcome = GroupOutcome.failed("internal_error", exc)
        finally:
            keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await keeper
        if lease.lost:
            return False
        return await group_store.finish(runtime, tenant, prompt_id, group_id, token, outcome)


async def run_group(runtime: Any, tenant: str, prompt_id: uuid.UUID, group_id: uuid.UUID) -> bool:
    """Claim the group's requested run and execute it; ``False`` if someone else has it."""
    lease_s = runtime.settings().step_lease_seconds
    with tenant_context(tenant):
        async with runtime.session_factory() as db:
            token = await group_lease.claim(db, tenant, prompt_id, group_id, _now(), lease_s)
            await finalize_session(db)
    if token is None:
        return False
    return await execute(runtime, tenant, prompt_id, group_id, token)
