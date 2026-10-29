"""Review fixes for the AI steps (Task 22, round 2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.ai.results import stored_size
from sm_images.ai.schema_safety import UnsafeSchema, check, output_model
from sm_images.models import Collection, PromptResult
from sm_images.models.enums import ReviewStatus
from sm_images.pipeline import registry
from sm_images.pipeline.orchestrate import rerun_image
from sqlalchemy import update

from tests.ai_support import add_prompt, results, use_ai_steps
from tests.pipeline_support import Scripted


@pytest.fixture(autouse=True)
def _ai_registry(pipe):
    use_ai_steps()
    yield
    registry.reset_registry()


async def test_a_plugin_that_sends_the_display_out_is_never_invoked_unsafe(pipe):
    """The gate is the executor's, before ``run()``: a plugin step that declares
    ``sends_display_out`` never sees bytes that may be unredacted."""
    sender = Scripted("acme.send")
    sender.sends_display_out = True
    read = []

    async def run(ctx):
        read.append(await ctx.read_display())
        return sender.outcome

    sender.fn = run
    use_ai_steps(sender)
    coll = await pipe.collection({"acme.send": {}}, protect_originals=True)
    img = await pipe.image(coll)
    await pipe.run(img)
    step = (await pipe.runs(img))["acme.send"]
    assert (step.status.value, step.error_code) == ("failed", "display_not_ready")
    assert sender.calls == 0 and read == []


async def test_the_ai_steps_ask_for_no_transport_retries(pipe, ai):
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert ai.resolved == [{"max_retries": 0}]


async def _enable(pipe, coll, sid) -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(pipeline_config={"steps": {sid: {}}})
        )
        await s.commit()


async def _review(pipe, row_id: int, data) -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(PromptResult)
            .where(PromptResult.id == row_id)
            .values(review_status=ReviewStatus.CORRECTED, reviewed_data=data)
        )
        await s.commit()


async def test_history_is_trimmed_oldest_first_to_fit_the_cap(pipe, ai):
    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    await _enable(pipe, coll, f"prompt:{prompt.id}")
    img = await pipe.image(coll)
    pipe.settings.step_output_max_bytes = 1500
    for n in range(7):
        ai.answer = f"answer {n}"
        if n:
            await rerun_image(pipe.runtime, "default", img, "force")
        else:
            await pipe.run(img)
        (row,) = await results(pipe, prompt.id)
        await _review(pipe, row.id, {"note": f"{n}" + "x" * 300})
    await rerun_image(pipe.runtime, "default", img, "force")
    (row,) = await results(pipe, prompt.id)
    assert row.status.value == "completed" and row.result_text == "answer 6"
    assert stored_size(row) <= 1500
    assert 0 < len(row.history) < 5  # the oldest went first
    assert row.history[0]["reviewed_data"]["note"].startswith("6")


async def test_a_cap_too_small_for_the_answer_alone_fails(pipe, ai):
    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    await _enable(pipe, coll, f"prompt:{prompt.id}")
    img = await pipe.image(coll)
    ai.answer = "first"
    await pipe.run(img)
    pipe.settings.step_output_max_bytes = 1
    ai.answer = "second"
    await rerun_image(pipe.runtime, "default", img, "force")
    run = (await pipe.runs(img))[f"prompt:{prompt.id}"]
    assert (run.status.value, run.error_code) == ("failed", "output_too_large")
    (row,) = await results(pipe, prompt.id)
    assert row.result_text == "first"


def test_nested_objects_honour_additional_properties_false():
    schema = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
            },
            "empty": {"type": "object", "additionalProperties": False},
        },
    }
    model = output_model(schema)
    model.model_validate({"inner": {"a": "x"}, "empty": {}})
    with pytest.raises(ValidationError):
        model.model_validate({"inner": {"a": "x", "b": 1}})
    with pytest.raises(ValidationError):
        model.model_validate({"empty": {"b": 1}})


@pytest.mark.parametrize(
    "prop",
    [
        {"type": "string", "enum": ["long"], "maxLength": 2},
        {"type": "string", "enum": ["ab"], "minLength": 3},
        {"type": "integer", "enum": [5], "maximum": 3},
        {"type": "string", "const": "abc", "maxLength": 1},
    ],
)
def test_an_enum_that_breaks_its_own_constraints_is_refused(prop):
    with pytest.raises(UnsafeSchema) as caught:
        check({"type": "object", "properties": {"a": prop}})
    assert caught.value.code == "invalid_schema"


def test_a_consistent_enum_is_fine():
    model = check(
        {"type": "object", "properties": {"a": {"type": "string", "enum": ["ab"], "maxLength": 2}}}
    )
    model.model_validate({"a": "ab"})
