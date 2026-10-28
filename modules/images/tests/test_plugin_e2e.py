"""A plugin end to end: discovered, run, frozen out, then uninstalled.

``images_testplugin`` (``tests/plugin_fixture``) is made discoverable the way
``test_extensions`` does it: the fixture directory on ``sys.path`` and the
``simple_module`` entry points monkeypatched to name it.
"""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sm_images.models.enums import StepStatus
from sm_images.pipeline import extensions, registry
from sm_images.pipeline.control import overview

from tests.pipeline_support import jpeg

FIXTURE = str(Path(__file__).parent / "plugin_fixture")
STEP = "testplugin.count_pixels"


def _eps(*values: str):
    def fake(group=None):
        assert group == "simple_module"
        return [SimpleNamespace(value=v) for v in values]

    return fake


def _install(monkeypatch, *, plugin: bool) -> None:
    """Boot the registry as a host with (or without) the plugin installed."""
    values = ["images_testplugin.module:TestPluginModule"] if plugin else []
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(*values))
    registry.reset_registry()
    extensions.load_extensions()


@pytest.fixture(autouse=True)
def _fixture_path(monkeypatch):
    monkeypatch.syspath_prepend(FIXTURE)
    yield
    registry.reset_registry()
    for name in [n for n in sys.modules if n.startswith("images_testplugin")]:
        del sys.modules[name]


async def _counted(pipe, monkeypatch):
    _install(monkeypatch, plugin=True)
    preset = registry.get_preset("testplugin")
    assert preset is not None and STEP in preset.pipeline
    coll = await pipe.collection(preset.pipeline, preset_id=preset.id)
    img = await pipe.image(coll, jpeg((30, 20)))
    await pipe.run(img)
    return coll, img


async def test_the_plugins_step_runs_and_its_output_is_stored(pipe, monkeypatch):
    _, img = await _counted(pipe, monkeypatch)
    run = (await pipe.runs(img))[STEP]
    assert run.status is StepStatus.COMPLETED
    assert run.output == {"pixels": 600}
    assert run.step_version == 1
    assert registry.get_step(STEP).calls == 1


def test_registering_outside_load_extensions_after_the_freeze_raises(monkeypatch):
    _install(monkeypatch, plugin=True)
    from images_testplugin.images_extensions import CountPixels

    late = CountPixels()
    late.id = "testplugin.late"
    with pytest.raises(registry.RegistryFrozenError):
        registry.register_step(late)
    with pytest.raises(registry.RegistryFrozenError):
        extensions.Registrar().register_step(late)
    assert registry.get_step("testplugin.late") is None


async def test_a_removed_plugin_leaves_results_readable_and_its_step_not_installed(
    pipe, monkeypatch
):
    coll, img = await _counted(pipe, monkeypatch)
    _install(monkeypatch, plugin=False)  # uninstalled; the host restarts
    assert registry.get_step(STEP) is None

    kept = (await pipe.runs(img))[STEP]
    assert (kept.status, kept.output) == (StepStatus.COMPLETED, {"pixels": 600})

    later = await pipe.image(coll)
    await pipe.run(later)
    never = (await pipe.runs(later))[STEP]
    assert (never.status, never.error_code, never.attempts) == (
        StepStatus.SKIPPED,
        "not_installed",
        0,
    )
    async with pipe.db_state.session_factory() as s:
        body = await overview(s, coll)
    entry = {e["id"]: e for e in body["steps"]}[STEP]
    assert (entry["installed"], entry["state"]) == (False, "not_installed")
    assert body["not_installed"] == 2
    assert (await pipe.runs(img))[STEP].output == {"pixels": 600}  # still untouched
