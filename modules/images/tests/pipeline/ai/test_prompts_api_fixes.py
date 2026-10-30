"""Review fixes for the prompt routes (Task 22, round 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sm_images.models import Image, StepRun
from sqlalchemy import select, update

from tests.support.access import EDITOR, MANAGER, OWNER, headers
from tests.support.prompts import BASE
from tests.support.prompts import create_prompt as _create


async def test_cost_gating_of_the_run_route(prompts_world, ai):
    """Ruling: a whole collection, or ``all``, is the owner's or a manager's;
    an edit share may run named images, ``missing`` or ``stale``."""
    pid = (await _create(prompts_world)).json()["id"]
    url = f"{BASE}/prompts/{pid}/run"
    ai.answer = "ok"
    named = {"image_ids": [prompts_world.iid]}
    assert (await prompts_world.c.post(url, json=named, headers=headers(EDITOR))).status_code == 202
    stale = {**named, "scope": "stale"}
    assert (await prompts_world.c.post(url, json=stale, headers=headers(EDITOR))).status_code == 202
    for body in ({}, {"scope": "missing"}, {**named, "scope": "all"}):
        got = await prompts_world.c.post(url, json=body, headers=headers(EDITOR))
        assert got.status_code == 403, body
    assert (
        await prompts_world.c.post(url, json={"scope": "all"}, headers=headers(OWNER))
    ).status_code == 202
    manager = await prompts_world.c.post(url, json={}, headers=headers(MANAGER))
    assert manager.status_code == 202


async def test_auto_run_is_the_owners_to_switch_on(prompts_world):
    assert (await _create(prompts_world, EDITOR, auto_run=True)).status_code == 403
    pid = (await _create(prompts_world, EDITOR)).json()["id"]
    url = f"{BASE}/prompts/{pid}"
    on = {"auto_run": True}
    assert (await prompts_world.c.patch(url, json=on, headers=headers(EDITOR))).status_code == 403
    assert (await prompts_world.c.patch(url, json=on, headers=headers(OWNER))).json()[
        "auto_run"
    ] is True
    off = await prompts_world.c.patch(url, json={"auto_run": False}, headers=headers(EDITOR))
    assert off.status_code == 200 and off.json()["auto_run"] is False
    made = await _create(prompts_world, OWNER, name="auto", auto_run=True)
    assert made.status_code == 201


async def test_inputs_on_an_image_prompt_answer_one_code(prompts_world):
    made = await _create(prompts_world, inputs="results")
    assert (made.status_code, made.json()["code"]) == (422, "invalid_prompt_inputs")
    pid = (await _create(prompts_world)).json()["id"]
    got = await prompts_world.c.patch(
        f"{BASE}/prompts/{pid}", json={"inputs": "both"}, headers=headers(OWNER)
    )
    assert (got.status_code, got.json()["code"]) == (422, "invalid_prompt_inputs")


async def test_a_700_deep_items_chain_is_refused(prompts_world):
    node: dict = {"type": "string"}
    for _ in range(700):
        node = {"type": "array", "items": node}
    schema = {"type": "object", "properties": {"a": node}}
    got = await _create(prompts_world, output_schema=schema)
    assert got.status_code == 422


async def test_delete_removes_the_runs_of_trashed_images_too(prompts_world, ai):
    pid = (await _create(prompts_world)).json()["id"]
    sid = f"prompt:{pid}"
    async with prompts_world.c.db_state.session_factory() as s:
        s.add(StepRun(image_id=uuid.UUID(prompts_world.iid), step=sid))
        await s.execute(
            update(Image)
            .where(Image.id == uuid.UUID(prompts_world.iid))
            .values(is_deleted=True, deleted_at=datetime.now(UTC))
        )
        await s.commit()
    assert (
        await prompts_world.c.delete(f"{BASE}/prompts/{pid}", headers=headers(OWNER))
    ).status_code == 204
    async with prompts_world.c.db_state.session_factory() as s:
        left = (await s.execute(select(StepRun.step).where(StepRun.step == sid))).all()
    assert left == []
