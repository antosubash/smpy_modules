"""Group-scope prompts: member results, one consolidation, the cross-check.

Runs through :func:`sm_images.ai.group_request.request_groups` on the eager
``pipe`` runtime, against the fake model and meter of :mod:`tests.ai_support`.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_images.ai import group_members
from sm_images.models.enums import StepStatus

from tests.ai_support import add_prompt, results, use_ai_steps
from tests.group_support import (
    PHOTO,
    ROLES,
    answers,
    group_prompt,
    group_result,
    group_with,
    run_groups,
)
from tests.pipeline_support import Blur


@pytest.fixture
def pipe(file_pipe):
    return file_pipe


_answers = answers
_run = run_groups


async def test_one_consolidation_per_group_with_images(pipe, ai):
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, members = await group_with(pipe, coll, ROLES)
    prompt = await group_prompt(pipe, coll, inputs="images")
    assert await _run(pipe, prompt, group) == 1
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.result_data, row.model_name) == (
        StepStatus.COMPLETED,
        {"verdict": "ok"},
        "fake-vision",
    )
    assert row.prompt_revision == 1 and row.image_id is None
    assert ai.calls == 1 and len(ai.pictures) == len(members)
    assert ai.settings[0]["temperature"] == 0.0
    (charge,) = ai.charges
    assert charge["source"] == "images:group_prompt"
    assert charge["key"].startswith(f"images:default:group:{group.id}:prompt:{prompt.id}:1:")
    assert row.lease_token is None and row.lease_expires_at is None


async def test_members_are_reused_and_only_missing_ones_run(pipe, ai):
    ai.answer = _answers
    coll = await pipe.collection({}, group_roles=ROLES)
    group, members = await group_with(pipe, coll, ROLES)
    photo = await add_prompt(pipe, coll, output_schema=PHOTO, instruction="Count the trees.")
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    assert await _run(pipe, prompt, group) == 1
    assert sorted(r.image_id for r in await results(pipe, photo.id)) == sorted(members)
    assert ai.calls == 4  # three members, then the consolidation
    sources = [c["source"] for c in ai.charges]
    assert sources == ["images:prompt"] * 3 + ["images:group_prompt"]
    # the summary lists the member answers in role order, labelled by role
    text = ai.prompts[-1]
    assert text.index("centre") < text.index("left") < text.index("right")
    assert ai.pictures[3:] == []  # results only: no picture with the consolidation

    # again, everything current: the members are reused, one more consolidation
    assert await _run(pipe, prompt, group, "all") == 1
    assert ai.calls == 5
    assert [c["source"] for c in ai.charges][4:] == ["images:group_prompt"]


async def test_a_stale_member_result_is_run_again(pipe, ai):
    from sm_images.models import Prompt
    from sqlalchemy import update

    ai.answer = _answers
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:2])
    photo = await add_prompt(pipe, coll, output_schema=PHOTO, instruction="Count the trees.")
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await _run(pipe, prompt, group)
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Prompt).where(Prompt.id == photo.id).values(revision=2))
        await s.commit()
    await _run(pipe, prompt, group, "all")
    assert ai.calls == 6  # 2 + 1, then 2 again (revision 2) + 1
    assert {r.prompt_revision for r in await results(pipe, photo.id)} == {2}


async def test_member_runs_are_bounded_at_four(pipe, ai, monkeypatch):
    ai.answer = _answers
    coll = await pipe.collection({}, group_roles=[])
    group, _ = await group_with(pipe, coll, [f"r{i}" for i in range(7)])
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    live = peak = 0
    real = group_members.run_member

    async def slow(*args, **kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        try:
            return await real(*args, **kw)
        finally:
            live -= 1

    monkeypatch.setattr(group_members, "run_member", slow)
    await _run(pipe, prompt, group)
    assert peak == group_members.MEMBER_CONCURRENCY == 4
    assert ai.calls == 8


async def test_an_unsafe_member_display_fails_the_group_run(pipe, ai):
    use_ai_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}}, protect_originals=True, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:2])  # never processed: nothing redacted
    prompt = await group_prompt(pipe, coll, inputs="images")
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "display_not_ready")
    assert ai.calls == 0 and ai.charges == []


async def test_missing_member_results_store_the_summary_as_failed(pipe, ai):
    from sm_images.models import PromptResult

    ai.answer = lambda text: {"verdict": "partial"} if "Summarise" in text else {"wrong": True}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, (centre, _) = await group_with(pipe, coll, ROLES[:2])
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    async with pipe.db_state.session_factory() as s:  # centre already has its answer
        s.add(
            PromptResult(
                prompt_id=photo.id,
                image_id=centre,
                status=StepStatus.COMPLETED,
                result_data={"n": 1},
                prompt_revision=1,
            )
        )
        await s.commit()
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status is StepStatus.FAILED and row.result_data == {"verdict": "partial"}
    assert row.error.startswith("member_results_missing") and "left" in row.error
    assert "centre" not in row.error
    assert ai.calls == 2  # left's (invalid) answer, then the consolidation


async def test_no_usable_input_fails_without_a_charge(pipe, ai):
    ai.answer = {"wrong": True}  # every member answer is invalid
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:2])
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "no_usable_inputs")
    assert [c["source"] for c in ai.charges] == ["images:prompt"] * 2


async def test_quota_refusal_fails_the_group_run(pipe, ai):
    ai.admit = False
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "quota_exceeded")
    assert ai.calls == 0


async def test_an_empty_group_fails(pipe, ai):
    coll = await pipe.collection({})
    group, _ = await group_with(pipe, coll, [])
    prompt = await group_prompt(pipe, coll, inputs="images")
    await _run(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "group_empty")


async def test_scope_missing_skips_a_completed_group(pipe, ai):
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    assert await _run(pipe, prompt, group) == 1
    assert await _run(pipe, prompt, group, "missing") == 0
    assert await _run(pipe, prompt, group, "stale") == 0
    assert ai.calls == 1


async def test_a_whole_collection_group_run_stops_once_its_starter_lost_the_right(
    pipe, ai, monkeypatch
):
    """M7 for group scope: the starter is re-checked before each chunk of
    groups, so a revoked owner's run makes no further provider calls."""
    from sm_images.ai import group_request
    from sm_images.ai import run as prompt_run
    from sm_images.imports.access import OWNER
    from sm_images.models import Collection
    from sqlalchemy import update

    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    for _ in range(3):
        await group_with(pipe, coll, ROLES)
    prompt = await group_prompt(pipe, coll, inputs="images")
    monkeypatch.setattr(group_request, "CHUNK", 1)
    real = group_request.dispatch_group

    async def then_revoke(*a, **k):
        await real(*a, **k)
        async with pipe.db_state.session_factory() as s:
            await s.execute(
                update(Collection).where(Collection.id == coll.id).values(owner_id="gone")
            )
            await s.commit()

    monkeypatch.setattr(group_request, "dispatch_group", then_revoke)
    got = await prompt_run.run_prompt(
        pipe.runtime, "default", prompt.id, "missing", run_as="olga", access_basis=OWNER
    )
    assert (got, ai.calls) == (1, 1)
