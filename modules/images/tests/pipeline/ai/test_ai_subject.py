"""AI steps bill the collection owner in billing's ``user`` mode (#284).

An AI charge is a one-shot ``consume`` with no hold, so it bills the owner
derived now; the metering key is unchanged by the mode.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.pipeline import registry

from tests.support.ai import add_prompt, use_ai_steps
from tests.support.groups import (
    PHOTO,
    ROLES,
    answers,
    group_prompt,
    group_with,
    run_groups,
)


@pytest.fixture(autouse=True)
def _ai_registry(pipe):
    use_ai_steps()
    yield
    registry.reset_registry()


async def _classify(pipe, owner):
    coll = await pipe.collection({"classify": {}}, owner_id=owner)
    img = await pipe.image(coll)
    await pipe.run(img)
    return img


async def test_prompt_step_charges_owner_in_user_mode(pipe, ai, user_mode):
    pipe.runtime = user_mode.runtime(pipe.runtime)
    owner = str(uuid.uuid4())
    await _classify(pipe, owner)
    assert [c["tenant"] for c in ai.charges] == [f"user:{owner}"]


async def test_prompt_step_charges_tenant_in_tenant_mode(pipe, ai):
    await _classify(pipe, str(uuid.uuid4()))
    assert [c["tenant"] for c in ai.charges] == ["default"]


async def test_group_prompt_charges_owner_in_user_mode(file_pipe, ai, user_mode):
    pipe = file_pipe
    pipe.runtime = user_mode.runtime(pipe.runtime)
    owner = str(uuid.uuid4())
    ai.answer = answers
    coll = await pipe.collection({}, group_roles=ROLES, owner_id=owner)
    group, _ = await group_with(pipe, coll, ROLES)
    photo = await add_prompt(pipe, coll, output_schema=PHOTO)
    prompt = await group_prompt(pipe, coll, inputs="results", member=photo)
    await run_groups(pipe, prompt, group)
    assert ai.charges[-1]["tenant"] == f"user:{owner}"


async def test_group_prompt_charges_tenant_in_tenant_mode(file_pipe, ai):
    pipe = file_pipe
    ai.answer = {"verdict": "ok"}
    coll = await pipe.collection({}, group_roles=ROLES, owner_id=str(uuid.uuid4()))
    group, _ = await group_with(pipe, coll, ROLES[:1])
    prompt = await group_prompt(pipe, coll, inputs="images")
    await run_groups(pipe, prompt, group)
    assert ai.charges[-1]["tenant"] == "default"


async def test_ai_charge_key_unchanged_by_mode(pipe, ai, user_mode):
    await _classify(pipe, str(uuid.uuid4()))
    pipe.runtime = user_mode.runtime(pipe.runtime)
    await _classify(pipe, str(uuid.uuid4()))
    tenant_key, user_key = (c["key"] for c in ai.charges)
    assert [c["tenant"] == "default" for c in ai.charges] == [True, False]
    for key in (tenant_key, user_key):  # a digest of tenant, image, step: no subject in it
        assert key.startswith("images:step:") and "user:" not in key
    assert len(tenant_key) == len(user_key)
