"""The registry: what it accepts, what it refuses, and when it freezes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import pytest
from pydantic import BaseModel, ConfigDict, SecretBytes, SecretStr
from sm_events.calendar import extensions, registry
from sm_events.contracts.extensions import EventType, NoExtra


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    registry.reset_registry()
    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [])
    monkeypatch.setattr(extensions, "_plugins", list)
    yield
    registry.reset_registry()


class Src:
    id = "acme:x"
    label_key = "acme.x"
    public = False
    color = None
    icon = None
    settings_model = None

    async def occurrences(self, ctx, start, end):
        return []


def source(**changes):
    cls = type("S", (Src,), changes)
    return cls()


def talk(**changes):
    fields = {"id": "acme:t", "label_key": "k", "extra_model": NoExtra, **changes}
    return EventType(**fields)


def test_add_and_get():
    registry.add_source(Src(), namespace="acme")
    registry.add_type(talk(), namespace="acme")
    registry.freeze()
    assert registry.get_source("acme:x") is not None
    assert list(registry.plugin_sources()) == ["acme:x"]
    assert registry.get_type("acme:t") is not None
    assert registry.get_source("nope") is None


def test_duplicate_refused():
    registry.add_source(Src(), namespace="acme")
    with pytest.raises(registry.DuplicateExtension):
        registry.add_source(Src(), namespace="acme")
    registry.add_type(talk(), namespace="acme")
    with pytest.raises(registry.DuplicateExtension):
        registry.add_type(talk(), namespace="acme")


def test_namespace_must_match():
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_source(source(id="acme:x"), namespace="records")
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_type(talk(id="acme:t"), namespace="records")


@pytest.mark.parametrize(
    "ident", ["x", "acme:", "Acme:x", "acme:x y", "acme:" + "a" * 49, "acme:1x", ":x"]
)
def test_id_pattern(ident):
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_source(source(id=ident), namespace="acme")


def test_longest_id_accepted():
    registry.add_source(source(id="acme:" + "a" * 48), namespace="acme")


def test_builtin_ids_reserved():
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_source(source(id="events"), namespace="events")
    with pytest.raises(registry.InvalidExtensionId):
        registry.add_type(talk(id="event"), namespace="event")
    with pytest.raises(registry.InvalidExtensionId):
        registry.register_builtin_source(Src())
    with pytest.raises(registry.InvalidExtensionId):
        registry.register_builtin_type(talk())


class Sync(Src):
    def occurrences(self, ctx, start, end):  # not async
        return []


class SyncCheck(Src):
    def check_settings(self, sctx, settings):  # not async
        return None


class Forbidless(BaseModel):
    a: int = 1


class Broken(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    thing: Callable[[], int] | None = None


@pytest.mark.parametrize(
    "bad",
    [
        source(occurrences=None),
        Sync(),
        SyncCheck(),
        source(public="yes"),
        source(color="red"),
        source(icon="Bad Icon"),
        source(label_key=""),
        source(settings_model=dict),
        source(settings_model=Broken),
    ],
)
def test_source_protocol_checked(bad):
    with pytest.raises(registry.InvalidExtension):
        registry.add_source(bad, namespace="acme")


@pytest.mark.parametrize(
    "bad",
    [
        talk(extra_model=Forbidless),
        talk(extra_model=dict),
        talk(label_key=""),
        talk(icon="NO"),
    ],
)
def test_type_protocol_checked(bad):
    with pytest.raises(registry.InvalidExtension):
        registry.add_type(bad, namespace="acme")


def test_a_non_type_is_refused():
    with pytest.raises(registry.InvalidExtension):
        registry.add_type(object(), namespace="acme")  # type: ignore[arg-type]


def test_public_fields_must_be_model_fields():
    with pytest.raises(registry.InvalidExtension, match="public_fields"):
        registry.add_type(talk(public_fields=frozenset({"nope"})), namespace="acme")


def test_error_names_the_plugin():
    with pytest.raises(registry.InvalidExtension, match="acme"):
        registry.add_source(source(public="yes"), namespace="acme")


def test_frozen_after_load():
    extensions.load_extensions()
    assert registry.is_frozen()
    with pytest.raises(registry.RegistryFrozenError):
        registry.add_source(Src(), namespace="acme")
    with pytest.raises(registry.RegistryFrozenError):
        registry.add_type(talk(), namespace="acme")


class _Inner(BaseModel):
    token: SecretStr


def _sealed_like():
    from pydantic import PlainSerializer

    def seal_secret(value):
        return value

    return Annotated[str | None, PlainSerializer(seal_secret, return_type=str)]


def _model(**annotations):
    return type(
        "M", (BaseModel,), {"__annotations__": annotations, **dict.fromkeys(annotations)}
    )


@pytest.mark.parametrize(
    "model",
    [
        _model(key=SecretStr),
        _model(key=SecretBytes),
        _model(key=SecretStr | None),
        _model(keys=list[SecretStr]),
        _model(inner=_Inner),
        _model(inner=list[_Inner]),
        _model(key=_sealed_like()),
    ],
)
def test_secret_typed_settings_are_refused(model):
    with pytest.raises(registry.InvalidExtension, match="own module's settings"):
        registry.add_source(source(settings_model=model), namespace="acme")


def test_plain_settings_are_accepted():
    class Fine(BaseModel):
        name: str = "x"
        tags: list[str] = []

    registry.add_source(source(settings_model=Fine), namespace="acme")


def test_a_secret_in_an_event_types_extra_is_allowed():
    """Only source settings are stored in the clear in a calendar; ``extra`` is the event's own."""

    class Extra(BaseModel):
        model_config = ConfigDict(extra="forbid")
        note: str = ""

    registry.add_type(talk(extra_model=Extra), namespace="acme")
