from __future__ import annotations

import pytest
from sm_images.pipeline import registry as reg

from tests.step_support import FakeStep


@pytest.fixture(autouse=True)
def _clean():
    reg.reset_registry()
    yield
    reg.reset_registry()


def test_register_and_get():
    s = FakeStep("acme.one")
    reg.register_step(s)
    assert reg.get_step("acme.one") is s
    assert reg.get_step("acme.two") is None
    assert list(reg.all_steps()) == ["acme.one"]


def test_duplicate_step_fails():
    reg.register_step(FakeStep("acme.one"))
    with pytest.raises(reg.DuplicateStepError):
        reg.register_step(FakeStep("acme.one"))


@pytest.mark.parametrize(
    "sid", ["exif", "renditions", "quality", "anonymize", "classify", "prompt:x"]
)
def test_reserved_ids_refused_for_plugins(sid):
    with pytest.raises(reg.ReservedStepIdError):
        reg.register_step(FakeStep(sid))


@pytest.mark.parametrize("sid", ["plain", "Acme.one", "acme.", "acme.one.two", "1a.b", "acme-x.y"])
def test_plugin_ids_need_namespace(sid):
    with pytest.raises(reg.ReservedStepIdError):
        reg.register_step(FakeStep(sid))


def test_builtin_path_allows_only_reserved_ids():
    reg.register_builtin(FakeStep("exif"))
    with pytest.raises(reg.ReservedStepIdError):
        reg.register_builtin(FakeStep("acme.one"))


def test_unresolved_requires_fails_at_freeze():
    reg.register_step(FakeStep("acme.one", requires=("acme.missing",)))
    with pytest.raises(reg.UnresolvedRequiresError):
        reg.freeze()
    assert not reg.is_frozen()


def test_cyclic_requires_fails_at_freeze():
    reg.register_step(FakeStep("acme.a", requires=("acme.b",)))
    reg.register_step(FakeStep("acme.b", requires=("acme.a",)))
    with pytest.raises(reg.CyclicRequiresError):
        reg.freeze()


def test_late_registration_raises():
    reg.register_step(FakeStep("acme.one"))
    reg.freeze()
    assert reg.is_frozen()
    with pytest.raises(reg.RegistryFrozenError):
        reg.register_step(FakeStep("acme.two"))
    with pytest.raises(reg.RegistryFrozenError):
        reg.register_builtin(FakeStep("exif"))


def test_freeze_is_idempotent():
    reg.freeze()
    reg.freeze()
    assert reg.is_frozen()


def test_preset_register_duplicate_and_frozen():
    from sm_images.contracts import Preset

    reg.register_preset(Preset(id="acme", label_key="acme.l"))
    assert reg.get_preset("acme").id == "acme"
    with pytest.raises(reg.DuplicateStepError):
        reg.register_preset(Preset(id="acme", label_key="acme.l"))
    reg.freeze()
    with pytest.raises(reg.RegistryFrozenError):
        reg.register_preset(Preset(id="other", label_key="x"))


def test_topo_order_is_deterministic_and_name_sorted():
    reg.register_step(FakeStep("acme.c", requires=("acme.a",)))
    reg.register_step(FakeStep("acme.b"))
    reg.register_step(FakeStep("acme.a"))
    reg.register_step(FakeStep("acme.d", requires=("acme.c", "acme.b")))
    expected = ["acme.a", "acme.b", "acme.c", "acme.d"]
    assert reg.topo_order(["acme.d", "acme.c", "acme.b", "acme.a"]) == expected
    assert reg.topo_order(["acme.a", "acme.b", "acme.c", "acme.d"]) == expected


def test_topo_order_subset_ignores_outside_requires():
    reg.register_step(FakeStep("acme.a"))
    reg.register_step(FakeStep("acme.b", requires=("acme.a",)))
    assert reg.topo_order(["acme.b"]) == ["acme.b"]


def test_mutates_display_at_most_one():
    reg.register_step(FakeStep("acme.m1", mutates_display=True))
    reg.register_step(FakeStep("acme.m2", mutates_display=True))
    reg.register_step(FakeStep("acme.ok"))
    reg.check_display_mutators(["acme.m1", "acme.ok"])
    reg.check_display_mutators(["acme.m1", "gone.step"])
    with pytest.raises(reg.TooManyDisplayMutators):
        reg.check_display_mutators(["acme.m1", "acme.m2"])
