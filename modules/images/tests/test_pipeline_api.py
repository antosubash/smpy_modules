"""The pipeline API: overview, save (strict validation), restart and reprocess."""

from __future__ import annotations

import dataclasses
import uuid
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sm_images.models import Collection, StepRun, Visibility
from sm_images.models.enums import StepStatus
from sm_images.module import ImagesModule
from sm_images.pipeline.runtime import current_runtime, use_runtime
from sqlalchemy import select, update

from tests.access_support import (
    EDITOR,
    MANAGER,
    OWNER,
    STRANGER,
    VIEWER,
    collection,
    headers,
    image,
)
from tests.access_support import share as make_share
from tests.pipeline_support import Scripted, use_steps
from tests.stub_auth import as_user

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
    [(OWNER, 200), (MANAGER, 200), (EDITOR, 200), (VIEWER, 200), (STRANGER, 404), (None, 401)],
)
async def test_get_is_a_view_on_the_collection(world, who, expected):
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


# --- strict validation on save ---------------------------------------------------------------


async def put(world, steps):
    return await world.c.put(url(world), json={"steps": steps}, headers=headers(OWNER))


async def test_put_rejects_invalid_params_and_stores_nothing(world):
    r = await put(world, {"exif": {"bogus": 1}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pipeline_config"
    got = await world.c.get(url(world), headers=headers(OWNER))
    assert got.json()["config"] == {"steps": {"acme.x": {}, "acme.y": {}}}


async def test_put_rejects_an_enabled_step_whose_requires_is_off(world):
    for steps in (
        {"acme.y": {}},  # acme.x not in the config at all
        {"acme.x": {"enabled": False}, "acme.y": {}},  # present but disabled
    ):
        r = await put(world, steps)
        assert r.status_code == 422, steps
        assert "acme.x" in r.json()["detail"]
    assert (await put(world, {"acme.x": {}, "acme.y": {}})).status_code == 200
    off = {"acme.x": {"enabled": False}, "acme.y": {"enabled": False}}
    assert (await put(world, off)).status_code == 200


async def test_put_rejects_two_display_mutators_and_the_implicit_cycle(world):
    mut_a, mut_b = Scripted("acme.ma"), Scripted("acme.mb")
    mut_a.mutates_display = mut_b.mutates_display = True
    loop = Scripted("acme.loop", requires=("renditions",))
    loop.mutates_display = True
    use_steps(mut_a, mut_b, loop)
    two = await put(world, {"acme.ma": {}, "acme.mb": {}})
    assert two.status_code == 422 and "mutate" in two.json()["detail"]
    cycle = await put(world, {"renditions": {}, "acme.loop": {}})
    assert cycle.status_code == 422 and "cycle" in cycle.json()["detail"]
    assert (await put(world, {"acme.ma": {}, "renditions": {}})).status_code == 200


async def test_put_keeps_a_not_installed_step(world):
    r = await put(world, {"acme.gone": {"anything": 1}})
    assert r.status_code == 200
    assert r.json()["config"]["steps"]["acme.gone"] == {"anything": 1}


# --- restart and reprocess ---------------------------------------------------------------------


@pytest.fixture
def no_broker(monkeypatch):
    """An eager request must never go through Celery's publish path."""
    from sm_images import tasks

    def boom(*a, **k):
        raise AssertionError("restart_collection was sent through celery")

    monkeypatch.setattr(tasks.restart_collection, "delay", boom)
    monkeypatch.setattr(tasks.restart_collection, "apply_async", boom)
    monkeypatch.setattr(tasks.run_step, "delay", boom)


async def test_restart_all_runs_in_process_when_eager(world, no_broker):
    await run_all(world)
    assert (world.x.calls, world.y.calls) == (1, 1)
    r = await world.c.post(url(world, "/restart"), json={"scope": "all"}, headers=headers(OWNER))
    assert r.status_code == 202, r.text
    assert (world.x.calls, world.y.calls) == (2, 2)
    assert {k: v.attempts for k, v in (await runs(world)).items()} == {"acme.x": 2, "acme.y": 2}


async def test_restart_failed_reruns_only_what_failed_and_what_it_blocked(world, no_broker):
    from sm_images.pipeline.step import StepOutcome

    world.x.outcome = StepOutcome.failed("boom", "x")
    await run_all(world)
    world.x.outcome = StepOutcome.completed({})
    r = await world.c.post(url(world, "/restart"), json={"scope": "failed"}, headers=headers(OWNER))
    assert r.status_code == 202
    assert {k: v.status for k, v in (await runs(world)).items()} == {
        "acme.x": StepStatus.COMPLETED,
        "acme.y": StepStatus.COMPLETED,
    }


async def test_restart_bad_scope_is_422(world):
    r = await world.c.post(url(world, "/restart"), json={"scope": "some"}, headers=headers(OWNER))
    assert r.status_code == 422


async def test_restart_in_broker_mode_is_queued_with_the_tenant(world, monkeypatch):
    from sm_images import tasks

    use_runtime(dataclasses.replace(current_runtime(), eager=False))
    sig = MagicMock()
    monkeypatch.setattr(tasks.restart_collection, "s", MagicMock(return_value=sig))
    r = await world.c.post(url(world, "/restart"), json={"scope": "stale"}, headers=headers(OWNER))
    assert r.status_code == 202, r.text
    tasks.restart_collection.s.assert_called_once_with(world.cid, "stale")
    (kw,) = [c.kwargs for c in sig.apply_async.call_args_list]
    assert kw["queue"] == "images_imports" and "default" in kw["headers"].values()


def reprocess_url(world, iid: str | None = None) -> str:
    return f"/api/images/images/{iid or world.iid}/reprocess"


async def test_reprocess_retries_failed_and_force_reruns_everything(world, no_broker):
    from sm_images.pipeline.step import StepOutcome

    world.x.outcome = StepOutcome.failed("boom", "x")
    await run_all(world)
    world.x.outcome = StepOutcome.completed({})
    r = await world.c.post(reprocess_url(world), json={}, headers=headers(EDITOR))
    assert r.status_code == 202, r.text
    assert {k: v.status for k, v in (await runs(world)).items()}["acme.y"] is StepStatus.COMPLETED
    assert (world.x.calls, world.y.calls) == (2, 1)
    r = await world.c.post(reprocess_url(world), json={"force": True}, headers=headers(OWNER))
    assert r.status_code == 202
    assert (world.x.calls, world.y.calls) == (3, 2)


@pytest.mark.parametrize(
    ("who", "force", "expected"),
    [
        (OWNER, True, 202),
        (MANAGER, True, 202),
        (EDITOR, True, 403),
        (EDITOR, False, 202),
        (VIEWER, False, 403),
        (STRANGER, False, 404),
        (None, False, 401),
    ],
)
async def test_reprocess_permissions(world, who, force, expected):
    r = await world.c.post(reprocess_url(world), json={"force": force}, headers=headers(who))
    assert r.status_code == expected, r.text


async def test_reprocess_of_an_unknown_image_is_404(world):
    r = await world.c.post(
        reprocess_url(world, str(uuid.uuid4())), json={}, headers=as_user("olga", ("images.view",))
    )
    assert r.status_code == 404


async def test_reprocess_without_a_runtime_is_503(world):
    use_runtime(None)
    r = await world.c.post(reprocess_url(world), json={}, headers=headers(OWNER))
    assert r.status_code == 503
