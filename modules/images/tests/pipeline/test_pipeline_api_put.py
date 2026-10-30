"""Saving a pipeline: strict validation."""

from __future__ import annotations

from tests.support.access import OWNER, headers
from tests.support.pipeline import Scripted, use_steps
from tests.support.pipeline_api import url


async def put(world, steps):
    return await world.c.put(url(world), json={"steps": steps}, headers=headers(OWNER))


async def test_put_rejects_invalid_params_and_stores_nothing(world):
    r = await put(world, {"exif": {"bogus": 1}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pipeline_config"
    got = await world.c.get(url(world), headers=headers(OWNER))
    assert got.json()["config"] == {"steps": {"acme.x": {}, "acme.y": {}}}


async def test_put_rejects_an_enabled_step_whose_requires_is_off(world):
    for steps in (
        {"acme.y": {}},  # acme.x not in the config at all
        {"acme.x": {"enabled": False}, "acme.y": {}},  # present but disabled
    ):
        r = await put(world, steps)
        assert r.status_code == 422, steps
        assert "acme.x" in r.json()["detail"]
    assert (await put(world, {"acme.x": {}, "acme.y": {}})).status_code == 200
    off = {"acme.x": {"enabled": False}, "acme.y": {"enabled": False}}
    assert (await put(world, off)).status_code == 200


async def test_put_rejects_two_display_mutators_and_the_implicit_cycle(world):
    mut_a, mut_b = Scripted("acme.ma"), Scripted("acme.mb")
    mut_a.mutates_display = mut_b.mutates_display = True
    loop = Scripted("acme.loop", requires=("renditions",))
    loop.mutates_display = True
    use_steps(mut_a, mut_b, loop)
    two = await put(world, {"acme.ma": {}, "acme.mb": {}})
    assert two.status_code == 422 and "mutate" in two.json()["detail"]
    cycle = await put(world, {"renditions": {}, "acme.loop": {}})
    assert cycle.status_code == 422 and "cycle" in cycle.json()["detail"]
    assert (await put(world, {"acme.ma": {}, "renditions": {}})).status_code == 200


async def test_put_rejects_a_display_mutator_beside_an_uninstalled_step(world):
    mut = Scripted("acme.ma")
    mut.mutates_display = True
    use_steps(mut)
    r = await put(world, {"acme.ma": {}, "acme.gone": {}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pipeline_config"
    assert "acme.gone" in r.json()["detail"] and "not installed" in r.json()["detail"]
    # A prompt step never mutates, and a disabled unknown step runs nothing.
    off = {"acme.ma": {}, "prompt:caption": {}, "acme.gone": {"enabled": False}}
    assert (await put(world, off)).status_code == 200


async def test_put_keeps_a_not_installed_step(world):
    r = await put(world, {"acme.gone": {"anything": 1}})
    assert r.status_code == 200
    assert r.json()["config"]["steps"]["acme.gone"] == {"anything": 1}


async def test_put_rejects_a_two_step_requires_cycle(world, monkeypatch):
    """The registry refuses a cycle at freeze, so one reaches a save only through
    a registry that changed under the collection; the save must still refuse it."""
    from sm_images.pipeline import registry

    a, b = Scripted("acme.a", requires=("acme.b",)), Scripted("acme.b", requires=("acme.a",))
    use_steps()
    monkeypatch.setitem(registry._steps, "acme.a", a)
    monkeypatch.setitem(registry._steps, "acme.b", b)
    r = await put(world, {"acme.a": {}, "acme.b": {}})
    assert r.status_code == 422 and r.json()["code"] == "invalid_pipeline_config"
    assert "cycle" in r.json()["detail"]
