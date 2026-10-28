"""Reconcile's search for placeholder skips that can run now (phase 3 fix 5).

A run settled ``skipped``/``not_installed`` (its plugin was missing) or
``disabled`` is a placeholder: dispatch reopens it once the step is enabled
and installed (:func:`sm_images.pipeline.plan.reopenable`). Nothing dispatches
an image just because a plugin came back, so reconcile looks for them. Two
narrow reads: the distinct ``(collection, step)`` pairs that have such runs,
judged against each collection's config in Python, then the images of the
pairs that qualify.
"""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.plan import PLACEHOLDER_CODES
from sm_images.pipeline.runtime import Runtime

__all__ = ["reopenable_images"]


def _placeholders(tenant: str) -> list[Any]:
    """Placeholder runs of live images in live collections."""
    return [
        StepRun.tenant_id == tenant,
        Image.tenant_id == tenant,
        Image.is_deleted.is_(False),
        Collection.is_deleted.is_(False),
        StepRun.status == StepStatus.SKIPPED,
        StepRun.error_code.in_(sorted(PLACEHOLDER_CODES)),
    ]


def _joined(stmt: Any) -> Any:
    return stmt.join(Image, Image.id == StepRun.image_id).join(
        Collection, Collection.id == Image.collection_id
    )


async def reopenable_images(runtime: Runtime, tenant: str, ids: Any) -> list[uuid.UUID]:
    """Images with a placeholder run whose step is enabled and installed now.
    ``ids(stmt, column)`` pages a select (reconcile's keyset reader)."""
    # No JSON column under DISTINCT: Postgres has no equality operator for ``json``.
    pairs = _joined(select(Image.collection_id, StepRun.step).distinct()).where(
        *_placeholders(tenant)
    )
    async with runtime.session_factory() as db:
        rows = list((await db.execute(pairs)).all())
        configs = {}
        if rows:
            ids_ = sorted({c for c, _ in rows})
            stmt = select(Collection.id, Collection.pipeline_config).where(
                Collection.tenant_id == tenant, Collection.id.in_(ids_)
            )
            configs = dict((await db.execute(stmt)).all())
        await finalize_session(db)
    wanted: dict[uuid.UUID, list[str]] = {}
    for collection_id, step in rows:
        cfg = validate_pipeline_config(configs.get(collection_id), strict=False)
        sc = cfg.get(step)
        if sc is not None and sc.enabled and sc.state != "not_installed":
            wanted.setdefault(collection_id, []).append(step)
    out: list[uuid.UUID] = []
    for collection_id, steps in wanted.items():
        stmt = (
            _joined(select(StepRun.image_id).distinct())
            .where(*_placeholders(tenant))
            .where(Image.collection_id == collection_id, StepRun.step.in_(steps))
        )
        out += await ids(stmt, StepRun.image_id)
    return list(dict.fromkeys(out))
