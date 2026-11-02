"""Shared helpers of the map tests (Task 26): seeding located images, reading
the collection's map state, requesting a build, and a fake tippecanoe."""

from __future__ import annotations

import shutil
import uuid

import pytest
from simple_module_db import finalize_session
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.map import pmtiles_build, schedule
from sm_images.models import Collection
from sqlalchemy import select

T = DEFAULT_TENANT

__all__ = ["T", "fake_tippecanoe", "located", "request", "state", "web_runtime"]


async def located(pipe, coll, n: int, **kw) -> list[uuid.UUID]:
    out = []
    for i in range(n):
        out.append(await pipe.image(coll, lat=10.0 + i, lng=20.0 + i, **kw))
    return out


async def state(pipe, coll) -> Collection:
    async with pipe.db_state.session_factory() as s:
        return (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()


async def request(pipe, coll, *, force: bool = False) -> int | None:
    async with pipe.db_state.session_factory() as s:
        gen = await schedule.request(s, pipe.runtime, T, coll.id, force=force)
        await finalize_session(s)
    return gen


@pytest.fixture
def web_runtime(client):
    """The web process's runtime for ``client``'s app - so an after-commit
    archive delete or build hand-off happens - cleared afterwards, so no later
    test dispatches through this app's engine."""
    from sm_images.module import ImagesModule
    from sm_images.pipeline.runtime import current_runtime, use_runtime

    ImagesModule._use_runtime(client.app, client.db_state.session_factory)
    yield current_runtime()
    use_runtime(None)


@pytest.fixture
def fake_tippecanoe(monkeypatch):
    """No binary needed: ``convert`` copies the NDJSON to the output."""
    monkeypatch.setattr(pmtiles_build, "locate", lambda path: "/fake/tippecanoe")

    def convert(binary, src, out, count):
        shutil.copyfile(src, out)

    monkeypatch.setattr(pmtiles_build, "convert", convert)
