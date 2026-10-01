"""Running a schema preview out of request, on its own session — §8.9, F10.

A dry run over a type above ``preview_sync_limit`` records answers ``202`` and
finishes through :func:`sm_records.deferred.defer`, on a session of its own:
by the time a deferred job runs, the one that served the request has been
committed and closed (see :mod:`sm_records.deferred` for why that ordering is
the whole point). The job body lived in the endpoint while a preview was
something that only *read*.

It is here now because a ``rescan`` writes. "Check records" scans the schema
the records are stored against and records what it finds on each record's
``invalid_since`` (:mod:`sm_records.services._invalid`), so the deferred path
has the same problem :mod:`sm_records.services.reindex_runner` has and the
same answer: **this module commits**. Nothing else would — there is no request
and no ``get_db`` — and the marks would roll back silently at the end of the
``async with``, leaving a report on screen that claims a worklist the database
never learned about.

A draft preview still writes nothing, and its commit is a no-op over a
transaction that only read. That is worth one unconditional statement rather
than a branch: which of the two this call is depends on ``rescan``, and the
rule "the runner commits its own session" should not.

**It runs in the job's tenant** (tenancy design §A.5). The job records the
tenant of the type it was started for, and the whole run is inside
``tenant_scope(job.tenant_id)``. A deferred job arrives already bound to that
tenant, so the scope re-enters it. What it adds is that the runner is correct
on its own, whoever calls it.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from sm_records.models import RecordType
from sm_records.services import preview_jobs, schema_change
from sm_records.services.schema_change import MISSING
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope

__all__ = ["run_preview_job"]

logger = logging.getLogger(__name__)


async def run_preview_job(
    db_state: Any,
    job_id: str,
    type_id: int,
    fields: list[dict[str, Any]],
    *,
    display_field: Any = MISSING,
    slug_field: Any = MISSING,
    rescan: bool = False,
    settings: RecordsSettings,
) -> None:
    """The deferred half of ``POST /types/{key}/schema/preview``.

    The type is re-loaded by id rather than handed over as an instance, for
    the same reason the session is new: the one it was loaded on is gone.

    ``display_field``/``slug_field`` arrive already resolved to
    :data:`~sm_records.services.schema_change.MISSING` or to a value — a
    caller that left a pointer out must not be read as clearing it, and that
    distinction belongs to whoever parsed the request body.

    Every failure lands on the job, because the response went out long ago and
    there is nobody left to raise at. The poller reads it and the client's
    answer is to preview again.
    """
    job = preview_jobs.get(job_id)
    if job is None:  # pragma: no cover - only finished jobs are pruned
        return
    try:
        with tenant_scope(job.tenant_id):
            async with db_state.session_factory() as session:
                rtype = await session.get(RecordType, type_id)
                if rtype is None:  # pragma: no cover - the type was deleted mid-preview
                    preview_jobs.fail(job_id, "the type no longer exists")
                    return
                diff, report = await schema_change.preview(
                    session,
                    rtype,
                    fields,
                    settings,
                    display_field=display_field,
                    slug_field=slug_field,
                    rescan=rescan,
                    on_progress=partial(preview_jobs.progress, job_id),
                )
                # See the module docstring: a rescan's marks have no other way
                # of being committed, and a draft preview's commit is a no-op.
                await session.commit()
            preview_jobs.finish(job_id, diff, report)
    except Exception as exc:  # pragma: no cover - defensive; preview is tested directly
        logger.exception("records: deferred schema preview %s failed", job_id)
        preview_jobs.fail(job_id, str(exc))
