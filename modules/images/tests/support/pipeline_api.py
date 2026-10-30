"""Fixtures shared by the pipeline API tests (``test_pipeline_api*.py``)."""

from __future__ import annotations

import uuid

import pytest_asyncio
from sm_images.models import StepRun, Visibility
from sm_images.module import ImagesModule
from sm_images.pipeline.runtime import current_runtime
from sqlalchemy import select

from tests.support.access import (
    EDITOR,
    OWNER,
    VIEWER,
    collection,
    image,
)
from tests.support.access import share as make_share
from tests.support.pipeline import Scripted, use_steps

BASE = "/api/images/collections"


@pytest_asyncio.fixture
async def world(client, storage):
    """olga's private collection with one image, an edit share for eddie and a
    view share for vic; two scripted steps registered; the web runtime set."""
    x, y = Scripted("acme.x"), Scripted("acme.y", requires=("acme.x",))
    use_steps(x, y)
    ImagesModule._use_runtime(client.app, client.db_state.session_factory)
    coll = collection("pipe", Visibility.PRIVATE, OWNER)
    coll.pipeline_config = {"steps": {"acme.x": {}, "acme.y": {}}}
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.flush()
        pic = image(coll, "a.jpg")
        s.add_all([pic, make_share(coll, EDITOR, "edit"), make_share(coll, VIEWER, "view")])
        await s.commit()
    return type("W", (), {"cid": str(coll.id), "iid": str(pic.id), "x": x, "y": y, "c": client})


async def runs(world) -> dict[str, StepRun]:
    async with world.c.db_state.session_factory() as s:
        rows = (await s.execute(select(StepRun))).scalars()
        return {r.step: r for r in rows}


async def run_all(world) -> None:
    from sm_images.pipeline.orchestrate import submit_dispatch

    await submit_dispatch(current_runtime(), "default", uuid.UUID(world.iid))


def url(world, tail: str = "") -> str:
    return f"{BASE}/{world.cid}/pipeline{tail}"
