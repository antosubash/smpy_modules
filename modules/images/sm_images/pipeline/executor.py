"""Run one claimed step: load, work, store (spec §3's three phases).

* **Load** - one short read session: the run must still be ``running`` under
  this token with an unexpired lease (else the claim was lost and nothing
  happens), then the image, its collection's validated config and an
  immutable :class:`ImageRead`. The session closes before any work.
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
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.contracts.schemas import ImageRead
from sm_images.models import Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.advance import collection_config
from sm_images.pipeline.claim import LostLease, renew
from sm_images.pipeline.config import StepConfig
from sm_images.pipeline.finish import complete_step
from sm_images.pipeline.runtime import Runtime
from sm_images.pipeline.step import StepContext, StepOutcome

__all__ = ["Loaded", "Staging", "bounded", "run_step_async"]

logger = logging.getLogger(__name__)
MESSAGE_MAX = 2000


@dataclass
class Staging:
    """Executor-only writes a step leaves behind (``ctx._staging``)."""

    settings: Any
    display: tuple[bytes, str] | None = None
    renditions: dict[str, tuple[bytes, int, int]] | None = None
    exif: Any = None


@dataclass(frozen=True)
class Loaded:
    tenant: str
    image_id: uuid.UUID
    step: str
    token: uuid.UUID
    image: ImageRead
    collection_id: uuid.UUID
    storage_key: str
    display_key: str | None
    display_generation: int
    config: StepConfig | None


def _now() -> datetime:
    return datetime.now(UTC)


async def _load(runtime: Runtime, tenant: str, image_id: uuid.UUID, step: str, token: uuid.UUID):
    now = _now()
    async with runtime.session_factory() as db:
        where = [StepRun.tenant_id == tenant, StepRun.image_id == image_id, StepRun.step == step]
        run = (await db.execute(select(StepRun).where(*where))).scalar_one_or_none()
        owned = (
            run is not None
            and run.status is StepStatus.RUNNING
            and run.lease_token == token
            and run.lease_expires_at is not None
            and run.lease_expires_at >= now
        )
        image = None
        if owned:
            stmt = select(Image).where(Image.id == image_id, Image.tenant_id == tenant)
            image = (await db.execute(stmt)).scalar_one_or_none()
        loaded = None
        if image is not None:
            cfg = await collection_config(db, tenant, image.collection_id)
            loaded = Loaded(
                tenant=tenant,
                image_id=image_id,
                step=step,
                token=token,
                image=ImageRead.from_row(image),
                collection_id=image.collection_id,
                storage_key=image.storage_key,
                display_key=image.display_key,
                display_generation=image.display_generation,
                config=cfg.get(step),
            )
        await finalize_session(db)  # read-only: closes the transaction before any work
    return loaded


def _failed(code: str, exc: BaseException | str) -> StepOutcome:
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    return StepOutcome.failed(code, text[:MESSAGE_MAX])


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
        return _failed("invalid_output", exc)
    if len(encoded) > max_bytes:
        return _failed(
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
        outcome = _failed("step_error", exc)
    finally:
        keeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keeper
    if lease.lost:
        return None
    if not isinstance(outcome, StepOutcome):
        return _failed("invalid_outcome", f"run() returned {type(outcome).__name__}")
    return outcome


async def _work(runtime: Runtime, loaded: Loaded, staging: Staging) -> StepOutcome | None:
    impl = registry.get_step(loaded.step)
    cfg = loaded.config
    if impl is None or cfg is None or not cfg.enabled or cfg.state == "not_installed":
        return StepOutcome("skipped", reason="not_installed", code="not_installed")
    if cfg.state == "invalid":
        return _failed(cfg.error or "invalid_config", "the saved params no longer validate")
    try:
        applies = impl.applies(loaded.image, cfg.params)
    except Exception as exc:
        return _failed("step_error", exc)
    if not applies:
        return StepOutcome.skipped("not_applicable")
    return await _run(runtime, loaded, impl, staging)


async def run_step_async(
    runtime: Runtime, tenant: str, image_id: uuid.UUID, step: str, token: uuid.UUID
) -> bool:
    """Execute one claimed run; ``True`` when its result was recorded."""
    settings = runtime.settings()
    loaded = await _load(runtime, tenant, image_id, step, token)
    if loaded is None:
        logger.info("images.pipeline.claim_lost step=%s image=%s", step, image_id)
        return False
    impl = registry.get_step(step)
    version = impl.version if impl is not None else None
    staging = Staging(settings)
    try:
        outcome = await _work(runtime, loaded, staging)
    except Exception as exc:  # a soft time limit: record it (fenced), then re-raise
        failure = _failed("time_limit", exc)
        await complete_step(runtime, loaded, failure, Staging(settings), version=version)
        raise
    if outcome is None:
        logger.info("images.pipeline.lease_lost step=%s image=%s", step, image_id)
        return False
    outcome = bounded(outcome, settings.step_output_max_bytes)
    return await complete_step(runtime, loaded, outcome, staging, version=version)
