"""Review fixes for the AI steps (Task 22, round 1), through the executor."""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_images.models import Collection, Prompt, StepRun
from sm_images.pipeline import executor, registry
from sm_images.pipeline.advance import plan_and_claim
from sm_images.pipeline.config import validate_pipeline_config
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.pipeline.plan import effective_deps
from sqlalchemy import delete, update

from tests.support.ai import add_prompt, results, use_ai_steps
from tests.support.pipeline import Blur, Scripted


@pytest.fixture(autouse=True)
def _ai_registry(pipe):
    use_ai_steps()
    yield
    registry.reset_registry()


async def _claim(pipe, img, step: str):
    async with pipe.db_state.session_factory() as db:
        found = await plan_and_claim(db, "default", img, None, 600)
        await finalize_session(db)
    return next(c for c in found.claims if c.step == step)


async def test_a_redelivered_lease_calls_the_provider_once(pipe, ai, monkeypatch):
    """Two executions of one claim (a redelivered message): one provider call."""
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    claim = await _claim(pipe, img, "classify")
    completed = []

    async def hold(runtime, loaded, outcome, staging, *, version):
        completed.append(outcome)  # the first worker is still "working": no completion
        return False

    monkeypatch.setattr(executor, "complete_step", hold)
    await executor.run_step_async(pipe.runtime, "default", img, "classify", claim.token)
    await executor.run_step_async(pipe.runtime, "default", img, "classify", claim.token)
    assert ai.calls == 1
    assert len(completed) == 1  # the loser records nothing either


async def test_a_new_claim_may_call_again(pipe, ai):
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    await rerun_image(pipe.runtime, "default", img, "force")
    assert ai.calls == 2


async def test_invalid_output_is_one_call_and_fails(pipe, ai):
    ai.answer = {"labels": "not a list"}
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["classify"]
    assert (run.status.value, run.error_code) == ("failed", "invalid_output")
    assert ai.calls == 1  # no output-validation retry: one request per charge
    assert len(ai.charges) == 1


async def test_a_prompt_result_over_the_output_cap_fails_and_keeps_the_old_one(pipe, ai):
    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    await _enable(pipe, coll, f"prompt:{prompt.id}")
    img = await pipe.image(coll)
    ai.answer = "small"
    await pipe.run(img)
    ai.answer = "x" * (pipe.settings.step_output_max_bytes + 1)
    await rerun_image(pipe.runtime, "default", img, "force")
    run = (await pipe.runs(img))[f"prompt:{prompt.id}"]
    assert (run.status.value, run.error_code) == ("failed", "output_too_large")
    (row,) = await results(pipe, prompt.id)
    assert (row.status.value, row.result_text) == ("failed", "small")


async def test_a_requested_run_of_a_deleted_prompt_settles_not_installed(pipe, ai):
    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    img = await pipe.image(coll)
    sid = f"prompt:{prompt.id}"
    async with pipe.db_state.session_factory() as s:
        s.add(StepRun(image_id=img, step=sid))
        await s.execute(delete(Prompt).where(Prompt.id == prompt.id))
        await s.commit()
    await pipe.run(img)
    run = (await pipe.runs(img))[sid]
    assert (run.status.value, run.error_code) == ("skipped", "not_installed")


async def test_a_plugin_step_can_declare_it_sends_the_display_out():
    sender = Scripted("acme.send")
    sender.sends_display_out = True
    use_ai_steps(Blur(), sender)
    cfg = validate_pipeline_config({"steps": {"acme.blur": {}, "acme.send": {}}})
    assert effective_deps(cfg, "acme.send") == ["acme.blur"]
    plain = validate_pipeline_config({"steps": {"acme.blur": {}, "classify": {}}})
    assert effective_deps(plain, "classify") == ["acme.blur"]


def test_sends_display_out_must_be_a_bool():
    bad = Scripted("acme.bad")
    bad.sends_display_out = "yes"
    registry.reset_registry()
    with pytest.raises(registry.InvalidStepError):
        registry.register_step(bad)


async def _enable(pipe, coll, sid: str) -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(pipeline_config={"steps": {sid: {}}})
        )
        await s.commit()
