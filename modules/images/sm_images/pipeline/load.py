"""The executor's load phase (split from :mod:`.executor`).

One short read session: the run must still be ``running`` under this token
with an unexpired lease (else the claim was lost and nothing happens), then
the image, its collection's validated config - prompt steps resolved, and this
run's own prompt step even when the config does not enable it (a requested
run) - and an immutable :class:`ImageRead`. The session closes before any work.

For a step that sends the display copy out of the system (``classify``,
``prompt:*``) it also decides :attr:`Loaded.display_safe` the way serving
does: a trusted (redacted) display copy, or nothing pending redaction. The
planner already orders these steps after the display mutator; this catches
the cases it cannot see, such as a mutator whose plugin was uninstalled.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.contracts.schemas import ImageRead
from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.advance import collection_config
from sm_images.pipeline.config import StepConfig
from sm_images.pipeline.runtime import Runtime

__all__ = ["Loaded", "load_run", "sends_display_out"]

CLASSIFY = "classify"


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
    mutates_display: bool = False
    impl: Any = None
    """The registered step, or the prompt step resolved for this execution."""
    display_safe: bool = True


def sends_display_out(step: str) -> bool:
    return step == CLASSIFY or step.startswith(registry.PROMPT_PREFIX)


async def _display_safe(db: Any, tenant: str, image: Image) -> bool:
    from sm_images import redaction

    stmt = select(Collection).where(
        Collection.id == image.collection_id, Collection.tenant_id == tenant
    )
    collection = (await db.execute(stmt)).scalar_one_or_none()
    if collection is None:
        return False
    if redaction.trusts_display(collection, image):
        return True
    return not await redaction.pending(db, collection, image)


def _owned(run: StepRun | None, token: uuid.UUID, now: datetime) -> bool:
    return (
        run is not None
        and run.status is StepStatus.RUNNING
        and run.lease_token == token
        and run.lease_expires_at is not None
        and run.lease_expires_at >= now
    )


async def load_run(
    runtime: Runtime, tenant: str, image_id: uuid.UUID, step: str, token: uuid.UUID
) -> Loaded | None:
    now = datetime.now(UTC)
    async with runtime.session_factory() as db:
        where = [StepRun.tenant_id == tenant, StepRun.image_id == image_id, StepRun.step == step]
        run = (await db.execute(select(StepRun).where(*where))).scalar_one_or_none()
        image = None
        if _owned(run, token, now):
            stmt = select(Image).where(Image.id == image_id, Image.tenant_id == tenant)
            image = (await db.execute(stmt)).scalar_one_or_none()
        loaded = None
        if image is not None:
            requested = [step] if step.startswith(registry.PROMPT_PREFIX) else []
            cfg = await collection_config(db, tenant, image.collection_id, requested)
            impl = cfg.impl(step)
            if requested and impl is not None:
                from sm_images.ai import prompt_steps

                impl = await prompt_steps.full(db, tenant, impl)
            safe = True
            if sends_display_out(step):
                safe = await _display_safe(db, tenant, image)
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
                mutates_display=bool(getattr(impl, "mutates_display", False)),
                impl=impl,
                display_safe=safe,
            )
        await finalize_session(db)  # read-only: closes the transaction before any work
    return loaded
