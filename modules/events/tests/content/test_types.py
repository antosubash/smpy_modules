"""Event types: ``extra`` validation, its public subset and the type's description."""

from __future__ import annotations

import json

import pytest
from fastapi.exceptions import RequestValidationError
from sm_events.calendar.plugins import registry
from sm_events.content.types import public_extra, type_info, validate_extra
from sm_events.core import errors_extensions as err
from sm_events.core.errors import UnknownType

from tests.support.sources import acme_talk, install_talk


@pytest.fixture(autouse=True)
def talk(monkeypatch):
    install_talk(monkeypatch)
    yield
    registry.reset_registry()


def test_builtin_accepts_only_empty():
    assert validate_extra("event", {}) == {}
    with pytest.raises(RequestValidationError):
        validate_extra("event", {"anything": 1})


def test_plugin_extra_validated_and_dumped():
    got = validate_extra("acme:talk", {"speaker": "Ada"})
    assert got == {"speaker": "Ada", "room": None, "level": "intro"}
    assert json.dumps(got)  # plain JSON


def test_unknown_type():
    with pytest.raises(UnknownType):
        validate_extra("gone:thing", {})


def test_error_locs_under_extra_and_no_echo():
    with pytest.raises(RequestValidationError) as caught:
        validate_extra("acme:talk", {"level": "hunter2"})
    locs = {e["loc"] for e in caught.value.errors()}
    assert locs == {("body", "extra", "speaker"), ("body", "extra", "level")}
    assert "hunter2" not in str(caught.value.errors())
    with pytest.raises(RequestValidationError) as caught:
        validate_extra("acme:talk", {"speaker": "A", "surprise": 1})
    assert caught.value.errors()[0]["loc"] == ("body", "extra", "surprise")


def test_size_cap():
    with pytest.raises(err.ExtraTooLarge):
        validate_extra("acme:talk", {"speaker": "x" * 20_000})
    assert validate_extra("acme:talk", {"speaker": "x" * 1000})["speaker"]


def test_public_extra_filters_and_unknown_type_empty():
    extra = {"speaker": "A", "room": "secret", "level": "intro"}
    assert public_extra("acme:talk", extra) == {"speaker": "A"}
    assert public_extra("gone:thing", extra) == {}
    assert public_extra("event", extra) == {}
    assert public_extra("acme:talk", {}) == {}


def test_type_info():
    info = type_info(acme_talk())
    assert (info.id, info.builtin, info.public_fields, info.icon) == (
        "acme:talk",
        False,
        ["speaker"],
        "mic",
    )
    assert set(info.json_schema["properties"]) == {"speaker", "room", "level"}
    assert info.defaults == {"room": None, "level": "intro"}
    builtin = type_info(registry.get_type("event"))  # type: ignore[arg-type]
    assert builtin.builtin and builtin.defaults == {} and builtin.public_fields == []
