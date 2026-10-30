"""Staging a URL import's source: fetch it through ``safe_stream`` into a
spool, validate and count it, store it, and record key and count - the job
moves from ``staging`` to ``running`` in one fenced ``UPDATE``.

A newer generation that staged meanwhile wins: this attempt's object stays
behind its intent for the janitor, and the runner stops.
"""

from __future__ import annotations

from typing import IO

from simple_module_db import finalize_session
from sqlalchemy import update

from sm_images.imports import chunk, jobs, staging
from sm_images.imports.beat import beating
from sm_images.models import ImportJob
from sm_images.models.enums import JobStatus
from sm_images.pipeline.runtime import Runtime
from sm_images.storage.intents import clear_intents

__all__ = ["stage_source"]


async def stage_source(
    runtime: Runtime, tenant: str, job: jobs.JobSnap
) -> tuple[IO[bytes], jobs.JobSnap]:
    """Fetch, count and store a URL source; the job moves to ``running``."""
    settings = runtime.settings()

    async def beat() -> None:
        if not await jobs.heartbeat(runtime, tenant, job.id, job.generation):
            raise chunk.Stopped()

    assert job.source_url is not None
    source = await staging.fetch_source(
        job.source_url, max_bytes=settings.geojson_max_bytes, beat=beat
    )
    try:

        def beat_now():
            return beating(runtime, tenant, job.id, job.generation)

        async with beat_now():  # counting makes no database call
            total = await staging.count(source, settings.geojson_max_features)
        key = await staging.put_spool(
            runtime, tenant, job.id, source, job.generation, during=beat_now
        )
        async with runtime.session_factory() as db:
            stmt = (
                update(ImportJob)
                .where(
                    *jobs.where(tenant, job.id),
                    ImportJob.generation == job.generation,
                    ImportJob.status == JobStatus.STAGING,
                )
                .values(
                    source_key=key,
                    staged_keys=[key],
                    total_count=total,
                    checkpoint_index=0,
                    status=JobStatus.RUNNING,
                    heartbeat_at=jobs.now(),
                    updated_at=jobs.now(),
                )
                .returning(ImportJob.id)
                .execution_options(**jobs.SYNC)
            )
            if (await db.execute(stmt)).first() is None:
                await db.rollback()
                # A newer generation staged (or will stage) its own key; this
                # attempt's object stays behind its intent for the janitor.
                raise chunk.Stopped()
            await clear_intents(db, [key])
            await finalize_session(db)
    except BaseException:
        source.close()
        raise
    return source, jobs.JobSnap(
        **{**job.__dict__, "source_key": key, "total_count": total, "status": JobStatus.RUNNING}
    )
