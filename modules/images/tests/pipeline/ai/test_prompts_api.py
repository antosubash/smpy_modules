"""``/api/images/.../prompts`` and ``/api/images/prompts/{id}``: CRUD, results, run.

Reading is a view on the collection, everything else an edit. The runtime is
eager, so a run's AI call happens inside the request, against the fake model
of :mod:`tests.support.ai`.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.models import StepRun
from sqlalchemy import select

from tests.support.access import EDITOR, OWNER, STRANGER, VIEWER, headers
from tests.support.prompts import BASE, create_prompt

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
_create = create_prompt


async def _results(prompts_world, pid: str) -> list[dict]:
    got = await prompts_world.c.get(f"{BASE}/prompts/{pid}/results", headers=headers(OWNER))
    assert got.status_code == 200, got.text
    return got.json()["items"]


async def test_crud_by_right(prompts_world):
    made = await _create(prompts_world, EDITOR, output_schema=SCHEMA)
    assert made.status_code == 201, made.text
    pid = made.json()["id"]
    assert made.json()["revision"] == 1 and made.json()["inputs"] is None
    assert (await _create(prompts_world, VIEWER, name="other")).status_code == 403
    listed = await prompts_world.c.get(
        f"{BASE}/collections/{prompts_world.cid}/prompts", headers=headers(VIEWER)
    )
    assert [p["id"] for p in listed.json()["items"]] == [pid]
    for who, code in ((VIEWER, 200), (STRANGER, 404)):
        assert (
            await prompts_world.c.get(f"{BASE}/prompts/{pid}", headers=headers(who))
        ).status_code == code
    patch = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}", json={"auto_run": True}, headers=headers(VIEWER)
    )
    assert patch.status_code == 403
    gone = await prompts_world.c.delete(f"{BASE}/prompts/{pid}", headers=headers(EDITOR))
    assert gone.status_code == 204
    assert (
        await prompts_world.c.get(f"{BASE}/prompts/{pid}", headers=headers(OWNER))
    ).status_code == 404


async def test_an_unsafe_schema_is_refused(prompts_world):
    deep: dict = {"type": "string"}
    for _ in range(12):
        deep = {"type": "object", "properties": {"x": deep}}
    for schema in (deep, {"type": "object", "properties": {"a": {"$ref": "https://x/y.json"}}}):
        got = await _create(prompts_world, output_schema=schema)
        assert (got.status_code, got.json()["code"]) == (422, "unsafe_output_schema")
    pid = (await _create(prompts_world)).json()["id"]
    got = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}", json={"output_schema": deep}, headers=headers(OWNER)
    )
    assert (got.status_code, got.json()["code"]) == (422, "unsafe_output_schema")


async def test_inputs_belong_to_group_prompts(prompts_world):
    assert (await _create(prompts_world, inputs="results")).status_code == 422
    group = await _create(prompts_world, name="site", scope="group")
    assert group.json()["inputs"] == "images"
    pid = group.json()["id"]
    photo = (await _create(prompts_world, name="photo")).json()["id"]
    got = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}",
        json={"inputs": "both", "member_prompt_id": photo},
        headers=headers(OWNER),
    )
    assert got.json()["inputs"] == "both"
    assert (
        await _create(prompts_world, name="bad", scope="group", inputs="everything")
    ).status_code == 422
    run = await prompts_world.c.post(
        f"{BASE}/prompts/{pid}/run", json={"image_ids": [prompts_world.iid]}, headers=headers(OWNER)
    )
    assert (run.status_code, run.json()["code"]) == (422, "invalid_run_target")


async def test_names_are_unique_per_collection(prompts_world):
    assert (await _create(prompts_world)).status_code == 201
    dup = await _create(prompts_world)
    assert (dup.status_code, dup.json()["code"]) == (409, "prompt_name_taken")


async def test_prompt_edit_marks_results_stale(prompts_world, ai):
    ai.answer = {"n": 1}
    pid = (await _create(prompts_world, output_schema=SCHEMA)).json()["id"]
    run_url = f"{BASE}/prompts/{pid}/run"
    ran = await prompts_world.c.post(run_url, json={"scope": "missing"}, headers=headers(OWNER))
    assert (ran.status_code, ran.json()["requested"]) == (202, 1)
    (first,) = await _results(prompts_world, pid)
    assert (first["status"], first["result_data"], first["stale"]) == ("completed", {"n": 1}, False)

    renamed = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}", json={"name": "cows"}, headers=headers(OWNER)
    )
    assert renamed.json()["revision"] == 1  # a name is not what the model is asked
    edited = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}", json={"instruction": "Count the sheep."}, headers=headers(OWNER)
    )
    assert edited.json()["revision"] == 2
    (stale,) = await _results(prompts_world, pid)
    assert stale["stale"] is True and stale["prompt_revision"] == 1

    missing = await prompts_world.c.post(run_url, json={"scope": "missing"}, headers=headers(OWNER))
    assert missing.json()["requested"] == 0  # it has a result, if an old one
    ai.answer = {"n": 2}
    again = await prompts_world.c.post(run_url, json={"scope": "stale"}, headers=headers(OWNER))
    assert again.json()["requested"] == 1
    (fresh,) = await _results(prompts_world, pid)
    assert (fresh["stale"], fresh["result_data"], fresh["prompt_revision"]) == (False, {"n": 2}, 2)


async def test_run_only_named_images_of_the_collection(prompts_world, ai):
    pid = (await _create(prompts_world)).json()["id"]
    ai.answer = "ok"
    url = f"{BASE}/prompts/{pid}/run"
    other = await prompts_world.c.post(
        url, json={"image_ids": [str(uuid.uuid4())]}, headers=headers(OWNER)
    )
    assert other.json()["requested"] == 0
    mine = await prompts_world.c.post(
        url, json={"image_ids": [prompts_world.iid]}, headers=headers(OWNER)
    )
    assert mine.json()["requested"] == 1
    assert (await prompts_world.c.post(url, json={}, headers=headers(VIEWER))).status_code == 403


async def test_delete_removes_results_and_runs(prompts_world, ai):
    pid = (await _create(prompts_world)).json()["id"]
    ai.answer = "ok"
    await prompts_world.c.post(f"{BASE}/prompts/{pid}/run", json={}, headers=headers(OWNER))
    assert len(await _results(prompts_world, pid)) == 1
    await prompts_world.c.delete(f"{BASE}/prompts/{pid}", headers=headers(OWNER))
    async with prompts_world.c.db_state.session_factory() as s:
        rows = (await s.execute(select(StepRun.step))).scalars().all()
    assert f"prompt:{pid}" not in rows


async def test_run_without_the_ai_module_is_503(prompts_world, monkeypatch):
    import sm_images.pipeline.ai as ai_pkg

    pid = (await _create(prompts_world)).json()["id"]
    monkeypatch.setattr(ai_pkg, "ai_available", lambda: False)
    got = await prompts_world.c.post(f"{BASE}/prompts/{pid}/run", json={}, headers=headers(OWNER))
    assert (got.status_code, got.json()["code"]) == (503, "ai_unavailable")


@pytest.mark.parametrize("scope", ["missing", "stale", "all"])
async def test_a_pending_or_live_run_is_left_alone(scope):
    from datetime import UTC, datetime, timedelta

    from sm_images.models.enums import StepStatus
    from sm_images.pipeline.ai.run import wanted

    now = datetime.now(UTC)
    pending = StepRun(image_id=uuid.uuid4(), step="prompt:x", status=StepStatus.PENDING)
    live = StepRun(
        image_id=uuid.uuid4(),
        step="prompt:x",
        status=StepStatus.RUNNING,
        lease_expires_at=now + timedelta(minutes=5),
    )
    assert not wanted(pending, scope, 1, now) and not wanted(live, scope, 1, now)


async def test_a_null_for_a_required_field_changes_nothing(prompts_world):
    pid = (await _create(prompts_world)).json()["id"]
    body = {"instruction": None, "name": None, "auto_run": None}
    got = await prompts_world.c.patch(f"{BASE}/prompts/{pid}", json=body, headers=headers(OWNER))
    assert got.status_code == 200, got.text
    out = got.json()
    assert (out["instruction"], out["name"], out["revision"]) == ("Count the cows.", "count", 1)
