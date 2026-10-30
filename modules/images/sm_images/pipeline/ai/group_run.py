"""Run a group-scope prompt over one group (spec §3 "Group runs").

``run_group`` claims the group's result row (:mod:`.group_lease`) and
:func:`execute` works under that lease, renewed in the background:

1. **load** (:mod:`.group_load`) - the prompt, the members in role order;
2. **gates**, before anything is sent or charged: an empty or oversized group,
   a member whose picture this run would send but whose display copy may not
   leave yet (``display_not_ready`` - the whole run, not that member: a
   consolidation never silently skips a photo for privacy; a member whose
   stored result is reused and whose picture is not sent needs no safe copy),
   an unsafe stored schema, an unconfigured model;
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
7. **the cross-check** - the prompt's preset's hook, pure, with no session open,
   in a worker thread under a timeout (:mod:`.cross_check`), its failure stored
   as ``{"error"}``; past the timeout the run fails ``time_limit``;
8. **store** (:mod:`.group_store`), fenced by the lease.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from simple_module_db import finalize_session, tenant_context

from sm_images.core.clock import utcnow as _now
from sm_images.pipeline import registry
from sm_images.pipeline.ai import cross_check, group_inputs, group_lease, group_load, group_store
from sm_images.pipeline.ai.group_store import GroupOutcome
from sm_images.pipeline.ai.reads import PromptResultRead
from sm_images.pipeline.ai.results import PromptWrite, write_size
from sm_images.pipeline.claim import LostLease
from sm_images.pipeline.keeper import stop as stop_keeper

__all__ = ["SOURCE", "execute", "metering_key", "run_group"]

logger = logging.getLogger(__name__)
SOURCE = "images:group_prompt"
NEEDS_MEMBERS = ("results", "both")
SENDS_IMAGES = ("images", "both")


def metering_key(tenant: str, job: Any, group_id: uuid.UUID, token: uuid.UUID) -> str:
    """``images:group:<digest>``: see :mod:`sm_images.core.billing.metering_keys`."""
    from sm_images.core.billing.metering_keys import digest_key

    return digest_key("images:group", tenant, group_id, job.prompt_id, job.revision, token)


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


def _output_type(job: Any) -> Any:
    from sm_images.pipeline.ai.schema_safety import output_model

    if job.output_schema is None:
        return str
    return output_model(job.output_schema, key=(job.prompt_id, job.revision))


async def _work(runtime: Any, job: Any, lease: _Lease) -> GroupOutcome:
    from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
    from sm_ai import contracts

    from sm_images.pipeline.ai.runner import run_structured
    from sm_images.pipeline.ai.schema_safety import UnsafeSchema

    members = job.group.members
    if not members:
        return GroupOutcome.failed("group_empty", "the group has no images")
    if job.too_many:
        return GroupOutcome.failed("group_too_large", f"over {group_load.MAX_MEMBERS} images")
    found: dict[uuid.UUID, Any] = {}
    need: list[uuid.UUID] = []
    if job.inputs in NEEDS_MEMBERS:
        if job.member is None:
            return GroupOutcome.failed("member_prompt_missing", "no image prompt to consolidate")
        found, need = await group_inputs.needed(runtime, job)
    # Only a picture that is sent must be safe to send: every member's when the
    # pictures go with the summary, otherwise those of the members that need a call.
    sent = {m.image_id for m in members} if job.inputs in SENDS_IMAGES else set(need)
    if unsafe := [i for i in job.unsafe if i in sent]:
        return GroupOutcome.failed("display_not_ready", f"{len(unsafe)} not redacted yet")
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
        reads, missing = await group_inputs.member_results(runtime, job, found, need)
    try:
        pictures = await group_inputs.pictures(runtime, job) if job.inputs in SENDS_IMAGES else []
    except group_inputs.DisplayNotReady as exc:
        return GroupOutcome.failed("display_not_ready", f"{exc} not redacted yet")
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
            group_inputs.instruction(job, reads), out_type, pictures, model=model, temperature=0.0
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
    try:
        checked = await cross_check.check(hook, job.group, [*reads, summary], limit)
    except cross_check.CrossCheckTimedOut as exc:
        return GroupOutcome.failed("time_limit", exc)
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
            await stop_keeper(keeper)
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
