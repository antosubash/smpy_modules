"""Run one claimed step: load, work, store (spec §3's three phases).

* **Load** - one short read session (:mod:`.load`): the run must still be
  ``running`` under this token with an unexpired lease (else the claim was
  lost and nothing happens), then the image, its collection's validated config
  and an immutable :class:`ImageRead`. The session closes before any work.
* **Work** - no session open. The step sees bytes only through its
  :class:`StepContext`; a long step renews its lease with
  ``await ctx.progress(pct)``, and an executor-owned coroutine renews it too
  while the step awaits. CPU-bound built-ins run in a thread.
* **Store** - :func:`sm_images.pipeline.finish.complete_step`. The output is
  first checked: JSON-serialisable (no NaN) and at most
  ``step_output_max_bytes`` once encoded, else the run fails with
  ``invalid_output``/``output_too_large`` and its writes are discarded.

A step raising is a ``failed`` run with a bounded message. A soft time limit
records a fenced failure and is re-raised; cancellation is never turned into a
result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from simple_module_db import finalize_session

from sm_images.clock import utcnow as _now
from sm_images.pipeline.claim import LostLease, renew
from sm_images.pipeline.finish import complete_step
from sm_images.pipeline.keeper import stop as stop_keeper
from sm_images.pipeline.load import Loaded, load_run
from sm_images.pipeline.runtime import Runtime
from sm_images.pipeline.step import (
    MESSAGE_MAX,
    StepContext,
    StepOutcome,
    failure,
    sends_display_out,
)

__all__ = ["Loaded", "Staging", "bounded", "run_step_async"]

logger = logging.getLogger(__name__)


@dataclass
class Staging:
    """Executor-only state a built-in step reads and the writes it leaves
    behind (``ctx._staging``)."""

    settings: Any
    display: tuple[bytes, str] | None = None
    renditions: dict[str, tuple[bytes, int, int]] | None = None
    exif: Any = None
    prompt: Any = None
    """A prompt step's result (``sm_images.ai.results.PromptWrite``)."""
    token: uuid.UUID | None = None
    """The run's lease token: part of an AI step's metering idempotency key."""
    session_factory: Any = None
    """The runtime's sessions, for metering outside a request."""
    display_safe: bool = True
    """Whether the display copy may leave the system (``Loaded.display_safe``)."""


def bounded(outcome: StepOutcome, max_bytes: int) -> StepOutcome:
    """Strict, compact JSON within ``max_bytes``; otherwise a failed outcome."""
    if outcome.status == "skipped" and outcome.reason and len(outcome.reason) > MESSAGE_MAX:
        return StepOutcome("skipped", reason=outcome.reason[:MESSAGE_MAX], code=outcome.code)
    if outcome.status != "completed":
        return outcome
    try:
        encoded = json.dumps(
            outcome.output, allow_nan=False, separators=(",", ":"), ensure_ascii=False
        ).encode()
    except (TypeError, ValueError) as exc:
        return failure("invalid_output", exc)
    if len(encoded) > max_bytes:
        return failure(
            "output_too_large", f"output is {len(encoded)} bytes; the limit is {max_bytes}"
        )
    return StepOutcome.completed(json.loads(encoded))


class _Lease:
    """Renew the run's lease: on demand (``ctx.progress``) and in the background."""

    def __init__(self, runtime: Runtime, loaded: Loaded, lease_s: int) -> None:
        self.runtime, self.loaded, self.lease_s = runtime, loaded, lease_s
        self.lost = False

    async def renew(self, _pct: int | None = None) -> None:
        l = self.loaded  # noqa: E741
        async with self.runtime.session_factory() as db:
            ok = await renew(db, l.tenant, l.image_id, l.step, l.token, _now(), self.lease_s)
            await finalize_session(db)
        if not ok:
            self.lost = True
            raise LostLease(f"{l.step} on {l.image_id}: lease lost")

    async def keep_alive(self) -> None:
        while not self.lost:
            await asyncio.sleep(max(self.lease_s / 3, 1))
            try:
                await self.renew()
            except LostLease:
                return
            except Exception:  # transient: the next round, or the completion, decides
                logger.warning("images.pipeline.renew_failed", exc_info=True)


async def _run(runtime: Runtime, loaded: Loaded, impl: Any, staging: Staging) -> StepOutcome | None:
    """The step's own work. ``None`` = the lease was lost mid-run."""
    store = runtime.store()
    lease = _Lease(runtime, loaded, staging.settings.step_lease_seconds)

    async def read_original() -> bytes:
        return await store.read(loaded.storage_key)

    async def read_display() -> bytes:
        return await store.read(loaded.display_key or loaded.storage_key)

    async def write_display(data: bytes, content_type: str) -> None:
        staging.display = (bytes(data), content_type)

    assert loaded.config is not None and loaded.config.params is not None
    ctx = StepContext(
        step=impl,
        image=loaded.image,
        params=loaded.config.params,
        tenant_id=loaded.tenant,
        read_display=read_display,
        read_original=read_original,
        write_display=write_display if impl.mutates_display else None,
        on_progress=lease.renew,
    )
    staging.token = loaded.token
    staging.session_factory = runtime.session_factory
    staging.display_safe = loaded.display_safe
    ctx._staging = staging
    keeper = asyncio.ensure_future(lease.keep_alive())
    try:
        outcome = await impl.run(ctx)
    except LostLease:
        return None
    except Exception as exc:
        from celery.exceptions import SoftTimeLimitExceeded

        if isinstance(exc, SoftTimeLimitExceeded):
            raise
        logger.warning("images.pipeline.step_raised step=%s", loaded.step, exc_info=True)
        outcome = failure("step_error", exc)
    finally:
        await stop_keeper(keeper)
    if lease.lost:
        return None
    if not isinstance(outcome, StepOutcome):
        return failure("invalid_outcome", f"run() returned {type(outcome).__name__}")
    return outcome


async def _work(runtime: Runtime, loaded: Loaded, staging: Staging) -> StepOutcome | None:
    impl = loaded.impl
    cfg = loaded.config
    if impl is None or cfg is None or not cfg.enabled or cfg.state == "not_installed":
        return StepOutcome("skipped", reason="not_installed", code="not_installed")
    if cfg.state == "invalid":
        return failure(cfg.error or "invalid_config", "the saved params no longer validate")
    try:
        applies = impl.applies(loaded.image, cfg.params)
    except Exception as exc:
        return failure("step_error", exc)
    if not applies:
        return StepOutcome.skipped("not_applicable")
    if sends_display_out(impl) and not loaded.display_safe:
        # Before ``run()``: a step that sends the display copy out (built-in or
        # plugin) never gets to read one that may be unredacted.
        return failure("display_not_ready", "the display copy is not redacted yet")
    return await _run(runtime, loaded, impl, staging)


async def run_step_async(
    runtime: Runtime, tenant: str, image_id: uuid.UUID, step: str, token: uuid.UUID
) -> bool:
    """Execute one claimed run; ``True`` when its result was recorded."""
    settings = runtime.settings()
    loaded = await load_run(runtime, tenant, image_id, step, token)
    if loaded is None:
        logger.info("images.pipeline.claim_lost step=%s image=%s", step, image_id)
        return False
    version = loaded.impl.version if loaded.impl is not None else None
    staging = Staging(settings)
    try:
        outcome = await _work(runtime, loaded, staging)
    except Exception as exc:
        from celery.exceptions import SoftTimeLimitExceeded

        # Record a fenced failure either way. A soft time limit is re-raised
        # for Celery; anything else is an executor bug, logged, not a time limit.
        timed_out = isinstance(exc, SoftTimeLimitExceeded)
        fenced = failure("time_limit" if timed_out else "internal_error", exc)
        await complete_step(runtime, loaded, fenced, Staging(settings), version=version)
        if timed_out:
            raise
        logger.exception("images.pipeline.internal_error step=%s image=%s", step, image_id)
        return False
    if outcome is None:
        logger.info("images.pipeline.lease_lost step=%s image=%s", step, image_id)
        return False
    outcome = bounded(outcome, settings.step_output_max_bytes)
    return await complete_step(runtime, loaded, outcome, staging, version=version)
