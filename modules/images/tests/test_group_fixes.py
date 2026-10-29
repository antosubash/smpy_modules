"""Task 23 review fixes: member calls not duplicated, the cross-check cannot
touch the stored summary, lost group runs are recovered, and display safety
is required only of members whose picture is sent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import tenant_context
from sm_images.ai import group_lease, group_members
from sm_images.models import PromptResult
from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.reconcile import reconcile_tenant
from sqlalchemy import update

from tests.ai_support import add_prompt, use_ai_steps
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


async def _stored(pipe, prompt_id, image_id, n=1):
    async with pipe.db_state.session_factory() as s:
        s.add(
            PromptResult(
                prompt_id=prompt_id,
                image_id=image_id,
                status=StepStatus.COMPLETED,
                result_data={"n": n},
                prompt_revision=1,
            )
        )
        await s.commit()


async def test_a_member_answered_meanwhile_is_not_run_again(pipe, ai):
    """A group run decided a member needed a call, but another run answered it
    first: under the image lock the fresh result is reused."""
    ai.answer = answers
    coll = await pipe.collection({}, group_roles=ROLES)
    _, (img,) = await group_with(pipe, coll, ROLES[:1])
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    await _stored(pipe, photo.id, img)
    with tenant_context("default"):
        await group_members.run_members(pipe.runtime, "default", photo.id, 1, [img])
    assert ai.calls == 0 and ai.charges == []


async def test_two_group_prompts_sharing_a_member_call_it_once(pipe, ai):
    ai.answer = answers
    coll = await pipe.collection({}, group_roles=ROLES)
    group, members = await group_with(pipe, coll, ROLES)
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    one = await group_prompt(pipe, coll, inputs="results", member=photo, name="one")
    two = await group_prompt(pipe, coll, inputs="results", member=photo, name="two")
    await asyncio.gather(run_groups(pipe, one, group), run_groups(pipe, two, group))
    assert [c["source"] for c in ai.charges].count("images:prompt") == len(members)


async def test_the_cross_check_cannot_change_the_stored_summary(pipe, ai, monkeypatch):
    from sm_images.pipeline.presets import Preset

    def meddle(group, found):
        found[-1].result_data["verdict"] = "tampered"
        found[-1].result_data["nested"]["k"] = "tampered"
        return {"ok": True}

    preset = Preset(id="acme", label_key="acme.l", cross_check=meddle)
    monkeypatch.setattr(registry, "get_preset", lambda pid: preset)
    ai.answer = {"verdict": "ok", "nested": {"k": "v"}}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "nested": {"type": "object", "properties": {"k": {"type": "string"}}},
        },
    }
    prompt = await group_prompt(pipe, coll, inputs="images", output_schema=schema, preset_id="acme")
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.result_data == {"verdict": "ok", "nested": {"k": "v"}}
    assert row.cross_check == {"ok": True}


async def _age(pipe, prompt_id, **values):
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(PromptResult).where(PromptResult.prompt_id == prompt_id).values(**values)
        )
        await s.commit()


@pytest.mark.parametrize("lost", ["dispatch", "worker"])
async def test_reconcile_recovers_a_lost_group_run(pipe, ai, lost):
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    now = datetime.now(UTC)
    with tenant_context("default"):
        async with pipe.db_state.session_factory() as s:
            await group_lease.request(s, "default", prompt.id, group.id, "missing", 1, now, 600)
            await s.commit()
        if lost == "worker":  # claimed, then the worker died
            async with pipe.db_state.session_factory() as s:
                assert await group_lease.claim(s, "default", prompt.id, group.id, now, 600)
                await s.commit()
    old = now - timedelta(minutes=30)
    # requested long ago (and never claimed, or claimed and abandoned)
    await _age(pipe, prompt.id, requested_at=old, lease_expires_at=old)
    with tenant_context("default"):
        done = await reconcile_tenant(pipe.runtime, "default", datetime.now(UTC))
    assert done["group_runs"] == 1
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.result_data) == (StepStatus.COMPLETED, {"verdict": "ok"})


async def test_a_fresh_pending_group_run_is_left_to_its_dispatch(pipe, ai):
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    with tenant_context("default"):
        async with pipe.db_state.session_factory() as s:
            await group_lease.request(
                s, "default", prompt.id, group.id, "missing", 1, datetime.now(UTC), 600
            )
            await s.commit()
        done = await reconcile_tenant(pipe.runtime, "default", datetime.now(UTC))
    assert done["group_runs"] == 0 and ai.calls == 0


async def _protected(pipe):
    use_ai_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}}, protect_originals=True, group_roles=ROLES)
    group, members = await group_with(pipe, coll, ROLES[:2])  # never processed: nothing redacted
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    return coll, group, members, photo


async def test_reused_results_need_no_safe_display(pipe, ai):
    """inputs=results with every member answered: no picture leaves, so an
    unredacted display does not stop the summary."""
    ai.answer = {"verdict": "ok"}
    coll, group, members, photo = await _protected(pipe)
    for img in members:
        await _stored(pipe, photo.id, img)
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert row.status is StepStatus.COMPLETED, row.error
    assert ai.calls == 1 and ai.pictures == []


async def test_a_member_that_must_be_sent_still_needs_a_safe_display(pipe, ai):
    ai.answer = answers
    coll, group, members, photo = await _protected(pipe)
    await _stored(pipe, photo.id, members[0])  # the other one would need a call
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await run_groups(pipe, prompt, group)
    row = await group_result(pipe, prompt.id, group.id)
    assert (row.status, row.error.split(":")[0]) == (StepStatus.FAILED, "display_not_ready")
    assert ai.calls == 0 and ai.charges == []


async def test_recovery_ages_a_pending_run_by_its_request_not_its_last_write(pipe, ai):
    """Writes to a pending row (audit, a refused re-request) move ``updated_at``;
    reconcile ages it by ``requested_at``, which only entering pending sets."""
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES)
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    now = datetime.now(UTC)
    old = now - timedelta(minutes=30)
    with tenant_context("default"):
        async with pipe.db_state.session_factory() as s:
            await group_lease.request(s, "default", prompt.id, group.id, "missing", 1, old, 3600)
            await s.commit()
        for _ in range(3):  # re-requested while its dispatch lease runs: refused
            async with pipe.db_state.session_factory() as s:
                again = await group_lease.request(
                    s, "default", prompt.id, group.id, "all", 1, now, 3600
                )
                await s.commit()
            assert again is False
    await _age(pipe, prompt.id, created_at=now, updated_at=now)  # recent writes
    row = await group_result(pipe, prompt.id, group.id)
    assert row.requested_at == old
    with tenant_context("default"):
        done = await reconcile_tenant(pipe.runtime, "default", now)
    assert done["group_runs"] == 1
    assert (await group_result(pipe, prompt.id, group.id)).status is StepStatus.COMPLETED
