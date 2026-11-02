"""Restart and reprocess."""

from __future__ import annotations

import dataclasses
import uuid
from unittest.mock import MagicMock

import pytest
from sm_images.models.enums import StepStatus
from sm_images.pipeline.runtime import current_runtime, use_runtime

from tests.support.access import EDITOR, MANAGER, OWNER, STRANGER, VIEWER, headers
from tests.support.pipeline_api import run_all, runs, url
from tests.support.stub_auth import as_user


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
    from sm_images.models import PipelineRestart
    from sqlalchemy import select

    async with world.c.db_state.session_factory() as s:
        (rid,) = (await s.execute(select(PipelineRestart.id))).scalars()
    tasks.restart_collection.s.assert_called_once_with(world.cid, "stale", str(rid))
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
