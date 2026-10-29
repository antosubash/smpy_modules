from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sm_images.pipeline import extensions
from sm_images.pipeline import registry as reg

from tests.step_support import FakeStep

FIXTURE = str(Path(__file__).parent / "plugin_fixture")
REAL_LOADERS = list(extensions._BUILTIN_LOADERS)


def _eps(*values):
    def fake(group=None):
        assert group == "simple_module"
        return [SimpleNamespace(value=v) for v in values]

    return fake


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reg.reset_registry()
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [])
    monkeypatch.syspath_prepend(FIXTURE)
    yield
    reg.reset_registry()
    for name in [n for n in sys.modules if n.startswith(("lucas_fixture", "broken_fixture"))]:
        del sys.modules[name]


def test_finds_fixture_images_extensions(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        _eps("lucas_fixture.module:Mod", "os.path:join", "no_such_pkg_xyz:Mod"),
    )
    extensions.load_extensions()
    assert list(reg.all_steps()) == ["lucas_fixture.count"]
    assert reg.get_preset("lucas_fixture") is not None
    assert reg.is_frozen()


def test_idempotent(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("lucas_fixture.module:Mod"))
    extensions.load_extensions()
    extensions.load_extensions()
    assert list(reg.all_steps()) == ["lucas_fixture.count"]


def test_builtin_loaders_run_first(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("lucas_fixture.module:Mod"))
    monkeypatch.setattr(
        extensions, "_BUILTIN_LOADERS", [lambda: reg.register_builtin(FakeStep("exif"))]
    )
    extensions.load_extensions()
    assert list(reg.all_steps()) == ["exif", "lucas_fixture.count"]


def test_registrar_exposes_only_registration():
    r = extensions.Registrar()
    assert not hasattr(r, "freeze")
    assert not hasattr(r, "register_builtin")


def test_failed_load_resets_so_retry_is_clean(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("lucas_fixture.module:Mod"))
    monkeypatch.setattr(
        extensions,
        "_BUILTIN_LOADERS",
        [lambda: reg.register_builtin(FakeStep("exif", requires=("quality",)))],
    )
    with pytest.raises(reg.UnresolvedRequiresError):
        extensions.load_extensions()
    assert not reg.is_frozen()
    assert reg.all_steps() == {}


_SCRIPT = """
import importlib.metadata, json
from types import SimpleNamespace
from sm_images.contracts import all_steps, load_extensions  # heavy imports first
from sm_images.pipeline.registry import all_presets
_ep = SimpleNamespace(value="lucas_fixture.module:Mod")
importlib.metadata.entry_points = lambda group=None: [_ep]
load_extensions()
print(json.dumps([sorted(all_steps()), sorted(all_presets())]))
"""


def test_registry_parity_fresh_process(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("lucas_fixture.module:Mod"))
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", REAL_LOADERS)
    extensions.load_extensions()
    here = [sorted(reg.all_steps()), sorted(reg.all_presets())]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([FIXTURE, os.environ.get("PYTHONPATH", "")])}
    out = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == here


def test_builtins_are_registered_by_default(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps())
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", REAL_LOADERS)
    extensions.load_extensions()
    quality = ["quality"] if importlib.util.find_spec("cv2") else []  # the [quality] extra
    from sm_images.ai import ai_available

    classify = ["classify"] if ai_available() else []  # the [ai] extra
    assert sorted(reg.all_steps()) == sorted(["exif", "renditions", *quality, *classify])


def test_plugin_package_import_error_is_not_swallowed(monkeypatch):
    """A plugin whose own ``__init__`` imports a missing dependency is a broken
    install, not "no images_extensions": the error must surface."""
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("broken_fixture.module:Mod"))
    with pytest.raises(ModuleNotFoundError) as exc:
        extensions.load_extensions()
    assert exc.value.name == "no_such_dependency_xyz"
    assert not reg.is_frozen()


def test_absent_parent_package_is_skipped_with_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps("no_such_pkg_xyz:Mod"))
    extensions.load_extensions()
    assert reg.is_frozen()
    assert "no_such_pkg_xyz" in caplog.text
