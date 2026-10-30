"""GeoJSON imports to test against: an eager pipeline runtime plus helpers.

``imp`` is the fixture: :func:`tests.support.pipeline.make_pipe`'s database,
store and eager runtime, an empty pipeline (imports are about rows, not steps),
and the intent session factory set as ``on_startup`` leaves it.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest_asyncio
from sm_images.imports import jobs, runner, staging
from sm_images.imports.mapping import Mapping
from sm_images.intents import use_session_factory
from sm_images.models import Collection, Group, Image, ImportItem, ImportJob
from sm_images.models.enums import ImportKind
from sm_images.pipeline import registry
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select

from tests.support.fetch import PUBLIC_IP, body
from tests.support.pipeline import Pipe, jpeg, make_pipe, use_steps

URL = ImportKind.GEOJSON_URL
B64 = ImportKind.GEOJSON_BASE64
HOST = "img.example"


def geojson(features: list[Any]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def feature(props: dict[str, Any] | None, point: tuple[float, float] | None = None) -> dict:
    geom = {"type": "Point", "coordinates": list(point)} if point else None
    return {"type": "Feature", "properties": props, "geometry": geom}


def b64(color: str = "red", size=(8, 6)) -> str:
    return base64.b64encode(jpeg(size, color)).decode()


@dataclass
class Imp:
    pipe: Pipe
    coll: Collection

    @property
    def runtime(self):
        return self.pipe.runtime

    def stored(self) -> list[str]:
        """Every object key in the store."""
        return self.pipe.keys()

    async def job(
        self,
        features: list[Any],
        kind: ImportKind = B64,
        coll: Collection | None = None,
        auto_run_prompts: bool = False,
        **mapping: Any,
    ) -> ImportJob:
        """A job whose source is staged, as the route leaves it (not yet run)."""
        mapping = mapping or ({"image_prop": "img"} if kind is B64 else {"url_prop": "url"})
        job_id = uuid.uuid4()
        coll = coll or self.coll
        key, total = await staging.put_upload(
            self.runtime, DEFAULT_TENANT, job_id, io.BytesIO(geojson(features)), 1000
        )
        return await jobs.create_job(
            self.runtime,
            DEFAULT_TENANT,
            coll.id,
            kind=kind,
            mapping=Mapping(**mapping),
            job_id=job_id,
            staged=(key, total),
            auto_run_prompts=auto_run_prompts,
        )

    async def run(self, job: ImportJob, generation: int | None = None) -> str:
        gen = job.generation if generation is None else generation
        return await runner.import_geojson_async(self.runtime, DEFAULT_TENANT, job.id, gen)

    async def reload(self, job: ImportJob) -> ImportJob:
        async with self.pipe.db_state.session_factory() as s:
            return (await s.execute(select(ImportJob).where(ImportJob.id == job.id))).scalar_one()

    async def items(self, job: ImportJob) -> list[ImportItem]:
        async with self.pipe.db_state.session_factory() as s:
            stmt = (
                select(ImportItem)
                .where(ImportItem.job_id == job.id)
                .order_by(ImportItem.feature_index)
            )
            return list((await s.execute(stmt)).scalars())

    async def statuses(self, job: ImportJob) -> list[str]:
        return [i.status.value for i in await self.items(job)]

    async def images(self, coll: Collection | None = None) -> list[Image]:
        coll = coll or self.coll
        async with self.pipe.db_state.session_factory() as s:
            stmt = (
                select(Image)
                .where(Image.collection_id == coll.id)
                .execution_options(include_deleted=True)
                .order_by(Image.created_at)
            )
            return list((await s.execute(stmt)).scalars())

    async def groups(self) -> dict[str, uuid.UUID]:
        async with self.pipe.db_state.session_factory() as s:
            rows = (
                await s.execute(select(Group).where(Group.collection_id == self.coll.id))
            ).scalars()
            return {g.key: g.id for g in rows}

    async def counts(self, job: ImportJob) -> tuple[str, int, int, int, int, int]:
        j = await self.reload(job)
        return (
            j.status.value,
            j.total_count,
            j.checkpoint_index,
            j.done_count,
            j.duplicate_count,
            j.failed_count,
        )


async def touch(imp: Imp, job: ImportJob) -> None:
    """Freshen a job's heartbeat (its runner looks alive)."""
    from datetime import UTC, datetime

    from sqlalchemy import update

    async with imp.pipe.db_state.session_factory() as s:
        stmt = (
            update(ImportJob).where(ImportJob.id == job.id).values(heartbeat_at=datetime.now(UTC))
        )
        await s.execute(stmt)
        await s.commit()


def serve_images(resolver, inner, *, fail: dict[str, Any] | None = None):
    """``img.example`` answers every path with a JPEG (or ``fail[path]``)."""
    resolver[HOST] = [PUBLIC_IP]
    fail = fail or {}

    def handler(request):
        path = request.url.path
        if path in fail:
            got = fail[path]
            return got(request) if callable(got) else got
        return body(jpeg((8, 6), "blue"))

    return inner(handler)


@pytest_asyncio.fixture
async def imp(tmp_path):
    use_steps()
    pipe = await make_pipe(tmp_path)
    use_session_factory(pipe.db_state.session_factory)
    coll = await pipe.collection({}, group_roles=["point", "north"])
    yield Imp(pipe, coll)
    await pipe.db_state.engine.dispose()
    registry.reset_registry()


@pytest_asyncio.fixture
async def file_imp(tmp_path):
    """``imp`` on a file database, for a test that runs sessions concurrently.

    The in-memory database serves every session the same connection, so a
    concurrent session closing (a heartbeat, a second download) ``ROLLBACK``s or
    ``COMMIT``s another's half-finished settlement; a file database gives each
    session its own connection and makes a write wait for SQLite's lock, as on
    a host (see ``tests/pg_support.make_db_state``, #209)."""
    from tests.pg_support import make_db_state

    use_steps()
    pipe = await make_pipe(tmp_path, await make_db_state(file=tmp_path / "imports.db"))
    use_session_factory(pipe.db_state.session_factory)
    coll = await pipe.collection({}, group_roles=["point", "north"])
    yield Imp(pipe, coll)
    await pipe.db_state.engine.dispose()
    registry.reset_registry()
