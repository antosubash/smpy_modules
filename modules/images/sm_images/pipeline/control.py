"""What the pipeline API needs beyond the executor: the overview a collection's
pipeline screen reads, and the two ways to start work (a restart, a reprocess).

Kept out of :mod:`.orchestrate` (at its size cap). Both launchers go through the
executor's in-process helpers when the runtime is eager - never
``restart_collection.delay()``/``run_task`` from a request: ``run_task`` raises
on the running loop and the on-commit runner swallows it, so the work would be
silently dropped. A broker-backed process hands the restart to the
``images_imports`` queue, stamped with the tenant.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Literal

from sqlalchemy import func, select

from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.orchestrate import Scope, rerun_image
from sm_images.pipeline.plan import is_stale
from sm_images.pipeline.restart import restart_collection_async, start_restart
from sm_images.pipeline.runtime import Runtime
from sm_images.services.present import prompt_names

__all__ = ["RESTART_SCOPES", "launch_restart", "overview", "reprocess"]

ApiScope = Literal["failed", "stale", "all"]
RESTART_SCOPES: dict[str, Scope] = {"failed": "retry", "stale": "stale", "all": "force"}
"""The API's words for the executor's scopes."""


def _step_entry(step_id: str, cfg: Any) -> dict[str, Any]:
    impl = cfg.impl(step_id)
    stored = cfg.get(step_id)
    enabled = stored.enabled if stored is not None else False
    params = stored.params.model_dump() if stored is not None and stored.params else {}
    if impl is None:
        return {"id": step_id, "installed": False, "state": "not_installed", "enabled": enabled}
    return {
        "id": step_id,
        "installed": True,
        "state": stored.state if stored is not None else "ok",
        "enabled": enabled,
        "params": params,
        "version": impl.version,
        "queue": impl.queue,
        "requires": list(impl.requires),
        "mutates_display": impl.mutates_display,
        "params_schema": impl.params_schema().model_json_schema(),
    }


def _labelled(entry: dict[str, Any], label: str | None) -> dict[str, Any]:
    """A prompt step's entry carries its prompt's ``label`` (the viewer's too)."""
    return entry if label is None else {**entry, "label": label}


async def _run_groups(db: Any, collection_id: uuid.UUID) -> list[Any]:
    stmt = (
        select(
            StepRun.step,
            StepRun.status,
            StepRun.step_version,
            StepRun.error_code,
            func.count().label("n"),
        )
        .join(Image, Image.id == StepRun.image_id)
        .where(Image.collection_id == collection_id)
        .group_by(StepRun.step, StepRun.status, StepRun.step_version, StepRun.error_code)
    )
    return list((await db.execute(stmt)).all())


async def _missing(db: Any, collection_id: uuid.UUID, steps: list[str]) -> int:
    """Planned images (any run) with no run of an enabled step: a step enabled
    after they were processed. Stale - "Re-run stale" plans it for them."""
    total = 0
    for sid in steps:
        has = select(StepRun.id).where(StepRun.image_id == Image.id)
        stmt = select(func.count(Image.id)).where(
            Image.collection_id == collection_id,
            has.exists(),
            ~has.where(StepRun.step == sid).exists(),
        )
        total += int((await db.execute(stmt)).scalar_one())
    return total


async def overview(db: Any, collection: Collection) -> dict[str, Any]:
    """The saved config, every registered step with its JSON schema, and the
    results' status, stale and not-installed counts (trashed images excluded)."""
    from sm_images.ai import prompt_steps

    prompts = await prompt_steps.resolve(db, collection.id, tenant=collection.tenant_id)
    cfg = validate_pipeline_config(collection.pipeline_config, strict=False, prompts=prompts)
    # An enabled prompt step is in both ``cfg.steps`` and ``cfg.prompts``: list it once.
    ids = list(dict.fromkeys([*registry.all_steps(), *cfg.steps, *cfg.prompts]))
    status: dict[str, dict[str, int]] = {}
    stale = not_installed = 0
    for step, st, version, code, n in await _run_groups(db, collection.id):
        status.setdefault(step, {})[st.value] = status.get(step, {}).get(st.value, 0) + n
        run = SimpleNamespace(step=step, status=st, step_version=version, error_code=code)
        stale += n if is_stale(run, cfg) else 0  # type: ignore[arg-type]
        not_installed += n if cfg.impl(step) is None else 0
    stale += await _missing(db, collection.id, list(cfg.runnable()))
    names = await prompt_names(db, collection, ids)  # a prompt step by its name
    return {
        "config": collection.pipeline_config or {"steps": {}},
        "preset_id": collection.preset_id,
        "steps": [_labelled(_step_entry(sid, cfg), names.get(sid)) for sid in ids],
        "status": status,
        "stale": stale,
        "not_installed": not_installed,
        "pending": sum(c.get(StepStatus.PENDING.value, 0) for c in status.values()),
    }


async def launch_restart(
    runtime: Runtime,
    tenant: str,
    collection_id: uuid.UUID,
    scope: ApiScope,
    *,
    run_as: str | None = None,
    access_basis: str | None = None,
) -> None:
    """Re-run a collection's steps: inline when eager, else on ``images_imports``.

    In broker mode the :class:`PipelineRestart` record commits *before* the
    message is published, and the message names it: a first delivery that is
    lost leaves a record whose heartbeat goes stale, and reconcile resumes it.
    ``run_as``/``access_basis`` (the starter's right) are recorded on it and
    re-checked by the runner.
    """
    inner = RESTART_SCOPES[scope]
    if runtime.is_eager():
        await restart_collection_async(
            runtime, tenant, collection_id, inner, run_as=run_as, access_basis=access_basis
        )
        return
    from background_tasks.tenant_context import TENANT_HEADER

    from sm_images.jobs.task_config import QUEUE_IMPORTS
    from sm_images.tasks import restart_collection

    restart_id = await start_restart(
        runtime, tenant, collection_id, inner, run_as=run_as, access_basis=access_basis
    )
    restart_collection.s(str(collection_id), inner, str(restart_id)).apply_async(
        queue=QUEUE_IMPORTS, headers={TENANT_HEADER: tenant}
    )


async def reprocess(
    runtime: Runtime, tenant: str, image_id: uuid.UUID, *, force: bool
) -> list[str]:
    """Reset (retry, or force for everything) one image and plan it now."""
    return await rerun_image(runtime, tenant, image_id, "force" if force else "retry")
