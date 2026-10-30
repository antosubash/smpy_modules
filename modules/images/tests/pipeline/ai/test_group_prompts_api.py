"""Group prompts over the API: the member link, running per group, name races."""

from __future__ import annotations

import uuid

import pytest
from sm_images.models import Group, Image
from sqlalchemy import update

from tests.support.access import EDITOR, OWNER, headers
from tests.support.prompts import BASE, create_prompt

PHOTO = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
SUMMARY = {"type": "object", "properties": {"verdict": {"type": "string"}}}


async def _group(world) -> str:
    """A group holding the world's one image."""
    async with world.c.db_state.session_factory() as s:
        group = Group(collection_id=uuid.UUID(world.cid), key="site-1")
        s.add(group)
        await s.flush()
        await s.execute(
            update(Image).where(Image.id == uuid.UUID(world.iid)).values(group_id=group.id)
        )
        await s.commit()
    return str(group.id)


async def test_a_results_group_prompt_names_an_image_prompt(prompts_world):
    photo = (await create_prompt(prompts_world, name="photo", output_schema=PHOTO)).json()["id"]
    no_member = await create_prompt(prompts_world, name="site", scope="group", inputs="results")
    assert (no_member.status_code, no_member.json()["code"]) == (422, "invalid_prompt_inputs")
    made = await create_prompt(
        prompts_world, name="site", scope="group", inputs="both", member_prompt_id=photo
    )
    assert made.status_code == 201, made.text
    assert made.json()["member_prompt_id"] == photo
    site = made.json()["id"]
    # a group prompt is not a member; an image prompt takes none
    for body in (
        {"name": "x", "scope": "group", "inputs": "results", "member_prompt_id": site},
        {"name": "y", "member_prompt_id": photo},
        {"name": "z", "scope": "group", "inputs": "images", "member_prompt_id": photo},
        {"name": "w", "scope": "group", "inputs": "results", "member_prompt_id": str(uuid.uuid4())},
    ):
        got = await create_prompt(prompts_world, **body)
        assert (got.status_code, got.json()["code"]) == (422, "invalid_prompt_inputs"), body
    # switching to images drops the need for a member, and changes the revision
    patched = await prompts_world.c.patch(
        f"{BASE}/prompts/{site}",
        json={"inputs": "images", "member_prompt_id": None},
        headers=headers(OWNER),
    )
    assert patched.status_code == 200, patched.text
    assert (patched.json()["member_prompt_id"], patched.json()["revision"]) == (None, 2)


async def test_an_image_prompt_in_use_cannot_be_deleted(prompts_world):
    photo = (await create_prompt(prompts_world, name="photo")).json()["id"]
    await create_prompt(
        prompts_world, name="site", scope="group", inputs="results", member_prompt_id=photo
    )
    got = await prompts_world.c.delete(f"{BASE}/prompts/{photo}", headers=headers(OWNER))
    assert (got.status_code, got.json()["code"]) == (409, "prompt_in_use")


async def test_run_a_group_prompt_on_named_groups(prompts_world, ai):
    ai.answer = {"verdict": "fine"}
    gid = await _group(prompts_world)
    made = await create_prompt(
        prompts_world, name="site", scope="group", output_schema=SUMMARY, instruction="Sum up."
    )
    pid = made.json()["id"]
    url = f"{BASE}/prompts/{pid}/run"
    ran = await prompts_world.c.post(url, json={"group_ids": [gid]}, headers=headers(EDITOR))
    assert (ran.status_code, ran.json()["requested"]) == (202, 1), ran.text
    got = await prompts_world.c.get(f"{BASE}/prompts/{pid}/results", headers=headers(OWNER))
    (row,) = got.json()["items"]
    assert (row["group_id"], row["image_id"], row["status"]) == (gid, None, "completed")
    assert row["result_data"] == {"verdict": "fine"} and row["cross_check"] is None
    again = await prompts_world.c.post(url, json={"group_ids": [gid]}, headers=headers(EDITOR))
    assert again.json()["requested"] == 0  # missing: done already
    # the whole collection, or everything again, is the owner's
    for body in ({}, {"group_ids": [gid], "scope": "all"}):
        assert (
            await prompts_world.c.post(url, json=body, headers=headers(EDITOR))
        ).status_code == 403
    assert (await prompts_world.c.post(url, json={"scope": "all"}, headers=headers(OWNER))).json()[
        "requested"
    ] == 1
    assert ai.calls == 2


@pytest.mark.parametrize("scope", ["image", "group"])
async def test_the_run_target_must_match_the_scope(prompts_world, scope):
    gid = await _group(prompts_world)
    pid = (await create_prompt(prompts_world, name="p", scope=scope)).json()["id"]
    body = {"image_ids": [prompts_world.iid]} if scope == "group" else {"group_ids": [gid]}
    got = await prompts_world.c.post(f"{BASE}/prompts/{pid}/run", json=body, headers=headers(OWNER))
    assert (got.status_code, got.json()["code"]) == (422, "invalid_run_target")


async def test_the_database_refuses_a_duplicate_name(prompts_world, monkeypatch):
    """Two creates racing past the service's check: the unique constraint is a 409."""
    from sm_images.web.services import prompts as service

    async def passes(*args, **kw):
        return None

    monkeypatch.setattr(service, "_name_free", passes)
    assert (await create_prompt(prompts_world, name="same")).status_code == 201
    dup = await create_prompt(prompts_world, name="same")
    assert (dup.status_code, dup.json()["code"]) == (409, "prompt_name_taken")
    other = (await create_prompt(prompts_world, name="other")).json()["id"]
    renamed = await prompts_world.c.patch(
        f"{BASE}/prompts/{other}", json={"name": "same"}, headers=headers(OWNER)
    )
    assert (renamed.status_code, renamed.json()["code"]) == (409, "prompt_name_taken")
