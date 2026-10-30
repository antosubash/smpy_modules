"""``classify`` and ``prompt:<id>`` through the executor (no network, no billing).

The model is a Pydantic AI ``FunctionModel`` returned by a patched
``sm_ai.contracts.resolve_model``; metering is a patched
``sm_ai.contracts.consume_requests`` (see :mod:`tests.support.ai`).
"""

from __future__ import annotations

import pytest
from sm_ai.contracts import AiNotConfiguredError
from sm_images.models.enums import ReviewStatus
from sm_images.pipeline import registry
from sm_images.pipeline.orchestrate import rerun_image
from sqlalchemy import update

from tests.support.ai import add_prompt, results, use_ai_steps
from tests.support.pipeline import Blur, jpeg


@pytest.fixture(autouse=True)
def _ai_registry(pipe):
    """After ``pipe``, which registers the built-ins without ``classify``."""
    use_ai_steps()
    yield
    registry.reset_registry()


async def test_classify_uses_resolve_model(pipe, ai):
    coll = await pipe.collection({"classify": {"vocabulary": ["tree", "road"]}})
    img = await pipe.image(coll, jpeg((2000, 1000)))
    await pipe.run(img)
    run = (await pipe.runs(img))["classify"]
    assert run.status.value == "completed", run.error_message
    assert run.output == {"labels": [{"label": "tree", "confidence": 0.9}], "model": "fake-vision"}
    assert run.step_version == 1
    # The picture went out scaled to max_side, and the vocabulary in the prompt.
    (picture,) = ai.pictures
    assert max(picture.size) == 1024
    assert "tree, road" in ai.prompts[0]


async def test_classify_sends_the_redacted_display_copy(pipe, ai):
    use_ai_steps(Blur())
    coll = await pipe.collection({"acme.blur": {}, "classify": {}})
    img = await pipe.image(coll, jpeg((64, 48), "red"))
    await pipe.run(img)
    assert (await pipe.status(img))["classify"] == "completed"
    (picture,) = ai.pictures
    r, g, _ = picture.convert("RGB").getpixel((5, 5))
    assert g > r  # the blurred (green) display copy, never the red original


async def test_metered_per_call(pipe, ai):
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    first = (await pipe.runs(img))["classify"]
    await rerun_image(pipe.runtime, "default", img, "force")
    assert len(ai.charges) == 2
    keys = [c["key"] for c in ai.charges]
    assert all(k.startswith("images:step:") and len(k) <= 121 for k in keys)
    assert keys[0] != keys[1]  # a new claim, a new charge; a redelivery of one is free
    assert all(c["source"] == "images:classify" for c in ai.charges)
    assert all(c["sf"] is pipe.runtime.session_factory for c in ai.charges)
    assert first.status.value == "completed"


async def test_quota_exceeded_fails_step(pipe, ai):
    ai.admit = False
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["classify"]
    assert (run.status.value, run.error_code) == ("failed", "quota_exceeded")
    assert ai.calls == 0  # refused before the provider is called
    assert run.attempts == 1  # and not retried


async def test_unconfigured_ai_fails_without_charging(pipe, ai, monkeypatch):
    from sm_ai import contracts

    def unconfigured(model_name=None, **kw):
        raise AiNotConfiguredError("chat_model", "Set a model.")

    monkeypatch.setattr(contracts, "resolve_model", unconfigured)
    coll = await pipe.collection({"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["classify"]
    assert (run.status.value, run.error_code) == ("failed", "ai_not_configured")
    assert ai.charges == []


async def test_nothing_is_sent_while_the_original_is_protected(pipe, ai):
    """A collection that protects its originals but has no installed mutator
    (its plugin was removed): the display copy may be unredacted."""
    coll = await pipe.collection({"classify": {}}, protect_originals=True)
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["classify"]
    assert (run.status.value, run.error_code) == ("failed", "display_not_ready")
    assert ai.calls == 0 and ai.charges == []


async def test_prompt_step_stores_a_structured_result(pipe, ai):
    coll = await pipe.collection({})
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}
    prompt = await add_prompt(pipe, coll, output_schema=schema)
    await _enable(pipe, coll, prompt)
    ai.answer = {"count": 3}
    img = await pipe.image(coll)
    await pipe.run(img)
    sid = f"prompt:{prompt.id}"
    run = (await pipe.runs(img))[sid]
    assert run.status.value == "completed", run.error_message
    assert (run.step_version, run.prompt_revision) == (1, 1)
    (row,) = await results(pipe, prompt.id)
    assert (row.status.value, row.result_data, row.model_name) == (
        "completed",
        {"count": 3},
        "fake-vision",
    )
    assert row.prompt_revision == 1 and row.review_status is ReviewStatus.UNREVIEWED
    assert ai.charges[0]["source"] == "images:prompt"
    assert ai.charges[0]["key"].startswith("images:prompt:")


async def test_prompt_step_free_text(pipe, ai):
    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    await _enable(pipe, coll, prompt)
    ai.answer = "a field with a fence"
    img = await pipe.image(coll)
    await pipe.run(img)
    (row,) = await results(pipe, prompt.id)
    assert (row.result_text, row.result_data) == ("a field with a fence", None)


async def test_rerun_resets_review_keeps_history(pipe, ai):
    coll = await pipe.collection({})
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    prompt = await add_prompt(pipe, coll, output_schema=schema)
    await _enable(pipe, coll, prompt)
    img = await pipe.image(coll)
    for n in range(7):
        ai.answer = {"n": n}
        if n == 0:
            await pipe.run(img)
        else:
            await rerun_image(pipe.runtime, "default", img, "force")
        (row,) = await results(pipe, prompt.id)
        assert row.review_status is ReviewStatus.UNREVIEWED
        assert row.result_data == {"n": n}
        await _review(pipe, row.id, {"n": n * 10})
    (row,) = await results(pipe, prompt.id)
    await rerun_image(pipe.runtime, "default", img, "force")
    (row,) = await results(pipe, prompt.id)
    assert row.review_status is ReviewStatus.UNREVIEWED and row.reviewed_data is None
    assert len(row.history) == 5
    assert [h["reviewed_data"] for h in row.history] == [{"n": v * 10} for v in (6, 5, 4, 3, 2)]
    assert row.history[0]["review_status"] == "corrected"
    assert row.history[0]["result_data"] == {"n": 6}


async def test_a_failed_rerun_keeps_the_previous_result(pipe, ai):
    from pydantic_ai.exceptions import ModelHTTPError

    coll = await pipe.collection({})
    prompt = await add_prompt(pipe, coll)
    await _enable(pipe, coll, prompt)
    ai.answer = "first"
    img = await pipe.image(coll)
    await pipe.run(img)
    ai.fail = ModelHTTPError(status_code=503, model_name="fake-vision", body="down")
    await rerun_image(pipe.runtime, "default", img, "force")
    (row,) = await results(pipe, prompt.id)
    assert (row.status.value, row.result_text) == ("failed", "first")
    assert row.error.startswith("ai_error")


async def test_a_stored_unsafe_schema_is_refused_at_run_time(pipe, ai):
    coll = await pipe.collection({})
    deep: dict = {"type": "string"}
    for _ in range(12):
        deep = {"type": "object", "properties": {"x": deep}}
    prompt = await add_prompt(pipe, coll, output_schema=deep)
    await _enable(pipe, coll, prompt)
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))[f"prompt:{prompt.id}"]
    assert (run.status.value, run.error_code) == ("failed", "unsafe_output_schema")
    assert ai.charges == []


async def test_absent_without_ai_module(pipe, ai, monkeypatch):
    import sm_images.ai as ai_pkg
    from sm_images.pipeline.extensions import load_extensions

    monkeypatch.setattr(ai_pkg, "ai_available", lambda: False)
    registry.reset_registry()
    load_extensions()
    assert registry.get_step("classify") is None
    coll = await pipe.collection({"classify": {}})
    prompt = await add_prompt(pipe, coll, auto_run=True)
    await _enable(pipe, coll, prompt, extra={"classify": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    status = await pipe.status(img)
    assert status["classify"] == "skipped" and status[f"prompt:{prompt.id}"] == "skipped"
    runs = await pipe.runs(img)
    assert runs["classify"].error_code == "not_installed"
    assert await results(pipe, prompt.id) == [] and ai.calls == 0


async def _enable(pipe, coll, prompt, extra=None) -> None:
    from sm_images.models import Collection

    steps = {**(extra or {}), f"prompt:{prompt.id}": {}}
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(pipeline_config={"steps": steps})
        )
        await s.commit()


async def _review(pipe, result_id: int, data) -> None:
    from datetime import UTC, datetime

    from sm_images.models import PromptResult

    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(PromptResult)
            .where(PromptResult.id == result_id)
            .values(
                review_status=ReviewStatus.CORRECTED,
                reviewed_data=data,
                reviewed_by="rita",
                reviewed_at=datetime.now(UTC),
            )
        )
        await s.commit()
