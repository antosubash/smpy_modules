"""Group runs against slow plugin code and a display copy replaced mid-run.

* The preset's cross-check is plugin code: it runs off the event loop (the
  lease keeps renewing meanwhile) and under a timeout, past which the run
  fails ``time_limit`` rather than hanging the worker.
* The display keys are read at load; a member's copy replaced before the
  pictures are read is re-resolved once. A member that is no longer in the
  group is left out; one whose new copy is not safe to send fails the run
  ``display_not_ready``, as the load gate would have.
"""

from __future__ import annotations

import time

import pytest
from sm_images.ai import cross_check, group_lease, group_load
from sm_images.models import Image
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sqlalchemy import update

from tests.support.groups import ROLES, group_prompt, group_result, group_with, run_groups
from tests.support.pipeline import jpeg


@pytest.fixture
def pipe(file_pipe):
    return file_pipe


def _preset(monkeypatch, check) -> None:
    from sm_images.pipeline.presets import Preset

    found = Preset(id="acme", label_key="acme.l", cross_check=check)
    monkeypatch.setattr(registry, "get_preset", lambda pid: found if pid == "acme" else None)


async def test_a_cross_check_past_its_timeout_fails_the_run(pipe, ai, monkeypatch):
    monkeypatch.setattr(cross_check, "CROSS_CHECK_TIMEOUT_S", 0.2)
    _preset(monkeypatch, lambda g, r: time.sleep(1.0) or {"late": True})
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images", preset_id="acme")
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "time_limit")


async def test_the_lease_keeps_renewing_while_the_cross_check_runs(pipe, ai, monkeypatch):
    pipe.settings.step_lease_seconds = 3  # renewed every second
    renewed = []
    real = group_lease.renew

    async def renew(*args, **kwargs):
        renewed.append(time.monotonic())
        return await real(*args, **kwargs)

    monkeypatch.setattr(group_lease, "renew", renew)
    window = {}

    def slow(group, results):
        window["start"] = time.monotonic()
        time.sleep(2.5)
        window["end"] = time.monotonic()
        return {"ok": True}

    _preset(monkeypatch, slow)
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images", preset_id="acme")
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status == StepStatus.COMPLETED and row.cross_check == {"ok": True}
    assert [t for t in renewed if window["start"] < t < window["end"]], "the loop was blocked"


def _after_load(monkeypatch, change) -> None:
    """Run ``change(job)`` once the job is loaded, before its pictures are read."""
    real = group_load.load

    async def load(*args, **kwargs):
        job = await real(*args, **kwargs)
        await change(job)
        return job

    monkeypatch.setattr(group_load, "load", load)


async def _replace_display(pipe, image_id, old_key: str, **values) -> None:
    store = pipe.runtime.store()
    new_key = f"{old_key}.v2.jpg"
    data = jpeg()
    await store.put(new_key, data, content_type="image/jpeg", size=len(data))
    await store.delete_keys([old_key])
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Image).where(Image.id == image_id).values(display_key=new_key, **values)
        )
        await s.commit()


async def _world(pipe):
    coll = await pipe.collection({}, group_roles=ROLES)
    group, members = await group_with(pipe, coll, ROLES)
    prompt = await group_prompt(pipe, coll, inputs="images")
    return group, members, prompt


async def test_a_display_copy_replaced_mid_run_is_re_resolved(pipe, ai, monkeypatch):
    ai.answer = {"verdict": "ok"}
    group, members, prompt = await _world(pipe)

    async def replace(job):
        first = members[0]
        await _replace_display(pipe, first, job.display_keys[first])

    _after_load(monkeypatch, replace)
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status == StepStatus.COMPLETED, row.error
    assert len(ai.pictures) == len(ROLES)


async def test_a_member_gone_mid_run_is_left_out(pipe, ai, monkeypatch):
    ai.answer = {"verdict": "ok"}
    group, members, prompt = await _world(pipe)

    async def trash(job):
        first = members[0]
        await _replace_display(pipe, first, job.display_keys[first], is_deleted=True)

    _after_load(monkeypatch, trash)
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status == StepStatus.COMPLETED, row.error
    assert len(ai.pictures) == len(ROLES) - 1


async def test_a_replaced_copy_that_is_not_safe_fails_display_not_ready(pipe, ai, monkeypatch):
    ai.answer = {"verdict": "ok"}
    group, members, prompt = await _world(pipe)

    async def unsafe(job):
        first = members[0]
        await _replace_display(pipe, first, job.display_keys[first])

        async def never(db, collection, image):
            return False

        monkeypatch.setattr(group_load, "_safe", never)

    _after_load(monkeypatch, unsafe)
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "display_not_ready")
    assert ai.pictures == []
