"""``GET /api/images/presets`` and applying a preset to a collection.

The ``images_testplugin`` fixture (``tests/plugin_fixture``) is installed the way
``test_plugin_e2e`` does it, so its preset is the registered one.
"""

from __future__ import annotations

import importlib.metadata
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sm_images.models import Collection, Prompt
from sm_images.pipeline import extensions, registry
from sqlalchemy import select

from tests.support.access import EDITOR, MANAGER, OWNER, STRANGER, VIEWER, headers
from tests.support.prompts import BASE, create_prompt

FIXTURE = str(Path(__file__).parent.parent / "plugin_fixture")


@pytest.fixture
def plugin(monkeypatch, prompts_world):
    """After ``prompts_world``, which froze a registry without plugins."""
    monkeypatch.syspath_prepend(FIXTURE)

    def eps(group=None):
        return [SimpleNamespace(value="images_testplugin.module:TestPluginModule")]

    monkeypatch.setattr(importlib.metadata, "entry_points", eps)
    registry.reset_registry()
    extensions.load_extensions()
    yield prompts_world
    registry.reset_registry()
    for name in [n for n in sys.modules if n.startswith("images_testplugin")]:
        del sys.modules[name]


def _apply(world, who=OWNER, preset="testplugin"):
    return world.c.post(
        f"{BASE}/collections/{world.cid}/apply-preset",
        json={"preset_id": preset},
        headers=headers(who),
    )


async def _state(world):
    async with world.c.db_state.session_factory() as s:
        coll = (
            await s.execute(select(Collection).where(Collection.id == uuid.UUID(world.cid)))
        ).scalar_one()
        stmt = select(Prompt).where(Prompt.collection_id == coll.id).order_by(Prompt.name)
        return coll, list((await s.execute(stmt)).scalars())


async def test_the_test_plugins_preset_is_listed(plugin):
    for who in (VIEWER, STRANGER):  # deployment-wide: no collection is involved
        got = await plugin.c.get(f"{BASE}/presets", headers=headers(who))
        assert got.status_code == 200, got.text
        (preset,) = got.json()["items"]
        assert preset["id"] == "testplugin" and preset["label_key"] == "testplugin.label"
        assert preset["group_roles"] == ["centre", "left", "right"]
        assert preset["has_cross_check"] is True
        assert [p["id"] for p in preset["prompts"]] == ["testplugin.photo", "testplugin.summary"]
        assert preset["prompts"][1]["member"] == "testplugin.photo"
    assert (await plugin.c.get(f"{BASE}/presets")).status_code == 401


async def test_applying_a_preset_is_idempotent(plugin):
    got = await _apply(plugin)
    assert got.status_code == 200, got.text
    assert [p["name"] for p in got.json()["created"]] == ["Trees per photo", "Trees per site"]
    coll, prompts = await _state(plugin)
    assert coll.preset_id == "testplugin" and coll.group_roles == ["centre", "left", "right"]
    assert "testplugin.count_pixels" in coll.pipeline_config["steps"]
    photo, site = prompts
    assert (photo.preset_prompt_id, photo.auto_run, photo.preset_id) == (
        "testplugin.photo",
        True,
        "testplugin",
    )
    assert (site.scope.value, site.inputs, site.member_prompt_id) == ("group", "results", photo.id)

    again = await _apply(plugin)
    assert again.status_code == 200 and again.json()["created"] == []
    coll2, prompts2 = await _state(plugin)
    assert [p.id for p in prompts2] == [p.id for p in prompts]
    assert coll2.pipeline_config == coll.pipeline_config


async def test_an_edited_preset_prompt_is_not_overwritten(plugin):
    await _apply(plugin)
    _, (photo, _) = await _state(plugin)
    patched = await plugin.c.patch(
        f"{BASE}/prompts/{photo.id}", json={"instruction": "Mine now."}, headers=headers(OWNER)
    )
    assert patched.status_code == 200
    await _apply(plugin)
    _, (photo2, _) = await _state(plugin)
    assert photo2.instruction == "Mine now."


@pytest.mark.parametrize(("who", "code"), [(EDITOR, 403), (VIEWER, 403), (STRANGER, 404)])
async def test_only_the_owner_or_a_manager_applies(plugin, who, code):
    assert (await _apply(plugin, who)).status_code == code
    assert (await _apply(plugin, MANAGER)).status_code == 200


async def test_an_unknown_preset_is_404(plugin):
    got = await _apply(plugin, preset="nope")
    assert (got.status_code, got.json()["code"]) == (404, "preset_not_found")


async def test_a_taken_name_refuses_the_whole_preset(plugin):
    assert (await create_prompt(plugin, name="Trees per site")).status_code == 201
    got = await _apply(plugin)
    assert (got.status_code, got.json()["code"]) == (409, "prompt_name_taken")
    coll, prompts = await _state(plugin)
    assert [p.name for p in prompts] == ["Trees per site"] and coll.preset_id is None


async def test_the_presets_group_prompt_runs_its_own_cross_check(plugin, ai):
    """End to end: the applied preset's group prompt summarises its image
    prompt's results, and the plugin's real ``agreement`` hook is stored."""
    from sm_images.models import Group, Image
    from sqlalchemy import update

    ai.answer = {"trees": 3}
    assert (await _apply(plugin)).status_code == 200
    _, (photo, site) = await _state(plugin)
    assert site.preset_id == "testplugin" and site.member_prompt_id == photo.id
    async with plugin.c.db_state.session_factory() as s:
        group = Group(collection_id=uuid.UUID(plugin.cid), key="site-1")
        s.add(group)
        await s.flush()
        await s.execute(
            update(Image)
            .where(Image.id == uuid.UUID(plugin.iid))
            .values(group_id=group.id, group_role="centre")
        )
        await s.commit()
    ran = await plugin.c.post(
        f"{BASE}/prompts/{site.id}/run", json={"group_ids": [str(group.id)]}, headers=headers(OWNER)
    )
    assert (ran.status_code, ran.json()["requested"]) == (202, 1), ran.text
    got = await plugin.c.get(f"{BASE}/prompts/{site.id}/results", headers=headers(OWNER))
    (row,) = got.json()["items"]
    assert (row["status"], row["result_data"]) == ("completed", {"trees": 3})
    assert row["cross_check"] == {"members": 1, "total": 3, "agrees": True}
    assert [c["source"] for c in ai.charges] == ["images:prompt", "images:group_prompt"]
