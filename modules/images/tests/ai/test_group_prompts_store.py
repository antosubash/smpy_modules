"""Group runs: the stored cross-check, the review reset, a redelivered lease."""

from __future__ import annotations

import pytest
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry

from tests.support.ai import add_prompt
from tests.support.groups import (
    PHOTO,
    ROLES,
    answers,
    group_prompt,
    group_result,
    group_with,
    run_groups,
)


@pytest.fixture
def pipe(file_pipe):
    return file_pipe


_answers = answers
_run = run_groups


async def test_the_cross_check_is_stored(pipe, ai, monkeypatch):
    seen = []

    def check(group, found):
        seen.append((group, found))
        return {"agree": True, "members": len(group.members)}

    _preset(monkeypatch, check)
    ai.answer = _answers
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES)
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo, preset_id="acme")
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.cross_check == {"agree": True, "members": 3}
    ((g, found),) = seen
    assert [m.role for m in g.members] == ROLES
    assert [r.role for r in found[:-1]] == ROLES and found[0].result_data == {"n": 2}
    assert found[-1].group_id == group.id and found[-1].result_data == {"verdict": "ok"}


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        (lambda g, r: 1 / 0, "ZeroDivisionError"),
        (lambda g, r: ["not", "a", "dict"], "not a dict"),
        (lambda g, r: {"x": float("nan")}, "JSON"),
        (lambda g, r: {"x": "y" * 5000}, "cross_check_too_large"),
    ],
)
async def test_a_failing_cross_check_is_captured(pipe, ai, monkeypatch, check, expected):
    _preset(monkeypatch, check)
    pipe.settings.step_output_max_bytes = 4096
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images", preset_id="acme")
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status is StepStatus.COMPLETED and row.result_data == {"verdict": "ok"}
    assert set(row.cross_check) == {"error"} and expected in row.cross_check["error"]


async def test_a_rerun_resets_the_review_and_keeps_history(pipe, ai):
    from datetime import UTC, datetime

    from sm_images.models import PromptResult
    from sm_images.models.enums import ReviewStatus
    from sqlalchemy import update

    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    await _run(pipe, prompt, group)
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(PromptResult)
            .where(PromptResult.group_id == group.id)
            .values(
                review_status=ReviewStatus.ACCEPTED,
                reviewed_by="olga",
                reviewed_at=datetime.now(UTC),
            )
        )
        await s.commit()
    ai.answer = {"verdict": "better"}
    await _run(pipe, prompt, group, "all")
    row = await group_result(pipe, prompt.id, group.id)
    assert row.review_status is ReviewStatus.UNREVIEWED and row.result_data == {"verdict": "better"}
    assert row.history[0]["review_status"] == "accepted"
    assert row.history[0]["result_data"] == {"verdict": "ok"}


async def test_a_redelivered_group_lease_calls_once(pipe, ai, monkeypatch):
    """The same claim executed twice (a redelivered message): one call, one charge."""
    from datetime import UTC, datetime

    from sm_images.ai import group_lease, group_run

    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    now = datetime.now(UTC)
    async with pipe.db_state.session_factory() as s:
        assert await group_lease.request(s, "default", prompt.id, group.id, "missing", 1, now, 600)
        await s.commit()
    async with pipe.db_state.session_factory() as s:
        token = await group_lease.claim(s, "default", prompt.id, group.id, now, 600)
        await s.commit()
    real_finish = group_run.group_store.finish

    async def held(*args, **kw):  # the first execution never gets to complete
        return True

    monkeypatch.setattr(group_run.group_store, "finish", held)
    first = await group_run.execute(pipe.runtime, "default", prompt.id, group.id, token)
    monkeypatch.setattr(group_run.group_store, "finish", real_finish)
    second = await group_run.execute(pipe.runtime, "default", prompt.id, group.id, token)
    assert (first, second) == (True, False)
    assert ai.calls == 1 and len(ai.charges) == 1


def _preset(monkeypatch, check):
    from sm_images.pipeline.presets import Preset

    found = Preset(id="acme", label_key="acme.l", cross_check=check)
    monkeypatch.setattr(registry, "get_preset", lambda pid: found if pid == "acme" else None)
