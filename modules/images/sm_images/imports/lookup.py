"""Loading a job for a control, and the refusals controls answer with."""

from __future__ import annotations

import uuid

from simple_module_db import finalize_session

from sm_images.errors import Conflict, NotFound
from sm_images.imports.jobs import load
from sm_images.models import ImportJob
from sm_images.pipeline.runtime import Runtime

__all__ = ["conflict", "get"]


def conflict(code: str, detail: str) -> Conflict:
    """A 409 whose ``code`` tells the console which control was refused and why."""
    err = Conflict(detail)
    err.code = code
    return err


async def get(runtime: Runtime, tenant: str, job_id: uuid.UUID) -> ImportJob:
    """The job in ``tenant``, or 404."""
    async with runtime.session_factory() as db:
        row = await load(db, tenant, job_id)
        if row is not None:
            db.expunge(row)  # a detached snapshot: the commit must not expire it
        await finalize_session(db)
    if row is None:
        raise NotFound("Import job not found")
    return row
