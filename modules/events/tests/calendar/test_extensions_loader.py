"""Discovery: which packages are probed, in which order, and what a failure leaves behind."""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sm_events.calendar.plugins import extensions, registry

FIXTURES = str(Path(__file__).parent.parent / "fixtures")


def _eps(*pairs):
    """``(name, value)`` entry points."""

    def fake(group=None):
        assert group == "simple_module"
        return [SimpleNamespace(name=n, value=v) for n, v in pairs]

    return fake


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    registry.reset_registry()
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [])
    monkeypatch.syspath_prepend(FIXTURES)
    yield
    registry.reset_registry()
    for name in [n for n in sys.modules if n.startswith(("acme_events", "broken_events"))]:
        del sys.modules[name]


ACME = ("acme", "acme_events.module:Mod")


def test_finds_fixture_plugin(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        _eps(ACME, ("path", "os.path:join"), ("ghost", "no_such_pkg_xyz:Mod")),
    )
    extensions.load_extensions()
    assert list(registry.plugin_sources()) == ["acme:talks"]
    assert list(registry.all_types()) == ["acme:talk"]
    assert registry.is_frozen()


def test_idempotent(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(ACME))
    extensions.load_extensions()
    extensions.load_extensions()
    assert list(registry.plugin_sources()) == ["acme:talks"]


def test_builtins_registered_first(monkeypatch):
    from sm_events.contracts.extensions import EventType, NoExtra

    seen = []

    def builtin():
        seen.append("builtin")
        registry.register_builtin_type(EventType(id="event", label_key="k", extra_model=NoExtra))

    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [builtin])
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(ACME))
    extensions.load_extensions()
    assert seen == ["builtin"]
    assert list(registry.all_types()) == ["event", "acme:talk"]


def test_registrar_exposes_only_registration():
    r = extensions.Registrar("acme")
    assert not hasattr(r, "freeze")
    assert not hasattr(r, "reset_registry")
    assert not hasattr(r, "register_builtin_source")
    assert {n for n in dir(r) if not n.startswith("_")} == {"add_source", "add_type"}


def test_namespace_is_the_entry_point_name(monkeypatch):
    """The fixture registers ``acme:*``; under another entry-point name it is refused."""
    monkeypatch.setattr(
        importlib.metadata, "entry_points", _eps(("other", "acme_events.module:Mod"))
    )
    with pytest.raises(registry.InvalidExtensionId, match="other"):
        extensions.load_extensions()
    assert not registry.is_frozen()


def test_failed_load_resets_so_retry_is_clean(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(("other", ACME[1])))
    with pytest.raises(registry.InvalidExtensionId) as caught:
        extensions.load_extensions()
    assert any("acme_events" in n for n in caught.value.__notes__)  # the plugin is named
    assert not registry.is_frozen()
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(ACME))
    extensions.load_extensions()
    assert list(registry.plugin_sources()) == ["acme:talks"]


def test_plugin_package_import_error_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        importlib.metadata, "entry_points", _eps(("broken", "broken_events.module:Mod"))
    )
    with pytest.raises(ModuleNotFoundError) as exc:
        extensions.load_extensions()
    assert exc.value.name == "no_such_dependency_xyz"
    assert not registry.is_frozen()


def test_absent_extensions_module_skipped(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(("os", "os.path:join")))
    extensions.load_extensions()
    assert registry.plugin_sources() == {}


def test_absent_parent_package_is_skipped_with_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(("ghost", "no_such_pkg_xyz:Mod")))
    with caplog.at_level("WARNING"):
        extensions.load_extensions()
    assert "no_such_pkg_xyz" in caplog.text
    assert registry.is_frozen()


def test_worker_first_read_loads(monkeypatch):
    """No ``load_extensions()`` call: a getter on a fresh process loads and freezes."""
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(ACME))
    assert not registry.is_frozen()
    assert registry.get_type("acme:talk") is not None
    assert registry.is_frozen()
    assert registry.get_source("acme:talks") is not None


def test_a_plugin_reading_the_registry_while_loading_does_not_recurse(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "entry_points", _eps(ACME))
    real = sys.modules.get("acme_events.events_extensions")
    assert real is None
    import acme_events.events_extensions as plugin

    original = plugin.register

    def register(r):
        assert registry.get_type("acme:talk") is None  # nothing yet, and no recursion
        original(r)

    monkeypatch.setattr(plugin, "register", register)
    extensions.load_extensions()
    assert registry.get_type("acme:talk") is not None
