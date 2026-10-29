"""The pipeline API: overview and access."""

from __future__ import annotations

import uuid

import pytest
from sm_images.models import Collection, StepRun
from sm_images.models.enums import StepStatus
from sqlalchemy import update

from tests.access_support import EDITOR, MANAGER, OWNER, STRANGER, VIEWER, headers
from tests.pipeline_api_support import run_all, runs, url


async def test_overview_lists_steps_with_schemas_and_counts(world):
    await run_all(world)
    async with world.c.db_state.session_factory() as s:  # y's result is from an older version
        await s.execute(update(StepRun).where(StepRun.step == "acme.y").values(step_version=0))
        s.add(
            StepRun(
                image_id=uuid.UUID(world.iid),
                step="acme.gone",
                status=StepStatus.SKIPPED,
                error_code="not_installed",
            )
        )
        await s.execute(
            update(Collection)
            .where(Collection.id == uuid.UUID(world.cid))
            .values(pipeline_config={"steps": {"acme.x": {}, "acme.y": {}, "acme.gone": {}}})
        )
        await s.commit()
    r = await world.c.get(url(world), headers=headers(OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    steps = {s["id"]: s for s in body["steps"]}
    assert steps["acme.x"]["installed"] and steps["acme.x"]["enabled"]
    assert steps["acme.x"]["params_schema"]["type"] == "object"
    assert steps["acme.y"]["requires"] == ["acme.x"] and steps["exif"]["queue"] == "images"
    assert steps["acme.gone"] == {
        "id": "acme.gone",
        "installed": False,
        "state": "not_installed",
        "enabled": True,
    }
    assert body["status"]["acme.x"] == {"completed": 1}
    assert (body["stale"], body["not_installed"]) == (1, 1)


async def test_not_installed_step_reported_never_scheduled(world):
    async with world.c.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == uuid.UUID(world.cid))
            .values(pipeline_config={"steps": {"acme.x": {}, "acme.gone": {}}})
        )
        await s.commit()
    await run_all(world)
    got = await runs(world)
    assert got["acme.x"].status is StepStatus.COMPLETED
    gone = got["acme.gone"]
    assert (gone.status, gone.error_code, gone.attempts) == (StepStatus.SKIPPED, "not_installed", 0)
    assert world.x.calls == 1
    body = (await world.c.get(url(world), headers=headers(OWNER))).json()
    assert body["not_installed"] == 1
    assert {s["id"]: s["installed"] for s in body["steps"]}["acme.gone"] is False


# --- access --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "expected"),
    [(OWNER, 200), (MANAGER, 200), (EDITOR, 200), (VIEWER, 403), (STRANGER, 404), (None, 401)],
)
async def test_get_is_an_edit_on_the_collection(world, who, expected):
    r = await world.c.get(url(world), headers=headers(who))
    assert r.status_code == expected, r.text


CONFIG = {"steps": {"acme.x": {"enabled": True}}}


@pytest.mark.parametrize(
    ("who", "expected"),
    [(OWNER, 200), (MANAGER, 200), (EDITOR, 403), (VIEWER, 403), (STRANGER, 404), (None, 401)],
)
async def test_put_is_owner_or_manage(world, who, expected):
    r = await world.c.put(url(world), json=CONFIG, headers=headers(who))
    assert r.status_code == expected, r.text
    if expected == 200:
        assert r.json()["config"] == CONFIG


@pytest.mark.parametrize(
    ("who", "expected"),
    [(OWNER, 202), (MANAGER, 202), (EDITOR, 403), (VIEWER, 403), (STRANGER, 404), (None, 401)],
)
async def test_restart_is_owner_or_manage(world, who, expected):
    r = await world.c.post(url(world, "/restart"), json={"scope": "all"}, headers=headers(who))
    assert r.status_code == expected, r.text
