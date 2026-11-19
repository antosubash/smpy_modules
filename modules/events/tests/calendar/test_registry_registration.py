"""The registration provider in the extension registry (PR 9): namespaced, unique, frozen."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import extensions, registry
from sm_events.contracts import extensions as contract

from tests.support.providers import provider


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    registry.reset_registry()
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [])
    monkeypatch.setattr(extensions, "_plugins", list)
    yield
    registry.reset_registry()


def test_namespaced():
    registry.add_registration_provider(provider(), namespace="records")
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_registration_provider(
            provider(ident="other:registration"), namespace="records"
        )
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_registration_provider(provider(ident="registration"), namespace="records")
    registry.freeze()
    assert registry.registration_provider("records:registration") is not None
    assert registry.registration_provider("records:other") is None
    assert [p.id for p in registry.registration_providers()] == ["records:registration"]


def test_registrar_adds_one():
    extensions.Registrar("records").add_registration_provider(provider())
    registry.freeze()
    assert registry.registration_provider("records:registration") is not None


def test_duplicate():
    registry.add_registration_provider(provider(), namespace="records")
    with pytest.raises(registry.DuplicateExtension):
        registry.add_registration_provider(provider(), namespace="records")


def test_frozen():
    registry.freeze()
    with pytest.raises(registry.RegistryFrozenError):
        registry.add_registration_provider(provider(), namespace="records")


def test_reset_forgets_providers():
    registry.add_registration_provider(provider(), namespace="records")
    registry.reset_registry()
    registry.freeze()
    assert registry.registration_provider("records:registration") is None


def test_no_provider_is_a_working_registry():
    registry.freeze()
    assert registry.registration_providers() == []


async def _sync(ctx, target):  # not a coroutine function: refused at registration
    return None


def test_malformed_provider_refused():
    def not_async(ctx, target):
        return None

    with pytest.raises(registry.InvalidExtension):
        registry.add_registration_provider(provider(check=not_async), namespace="records")
    with pytest.raises(registry.InvalidExtension):
        registry.add_registration_provider(provider(recipients=not_async), namespace="records")
    with pytest.raises(registry.InvalidExtension):
        registry.add_registration_provider(object(), namespace="records")  # type: ignore[arg-type]
    with pytest.raises(registry.InvalidExtension):
        registry.add_registration_provider(provider().__class__(  # an empty label
            id="records:registration", label_key="", check_target=provider().check_target,
            recipients=provider().recipients), namespace="records")  # fmt: skip


def test_contract_names():
    for name in (
        "RegistrationProvider",
        "RegistrationContext",
        "RegistrationTargetInfo",
        "Registrant",
        "RegistrationTargetError",
    ):
        assert name in contract.__all__
        assert getattr(contract, name) is not None
