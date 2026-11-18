"""The plugin-facing types: their shape and the one contract module that exports them."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError
from sm_events.calendar import extension_types
from sm_events.contracts import extensions
from sm_events.core import constants
from sm_events.models.enums import DEFAULT_EVENT_TYPE

TYPES = [
    "EventType",
    "NoExtra",
    "SettingsContext",
    "Source",
    "SourceCalendar",
    "SourceContext",
    "SourceError",
    "SourceOccurrence",
    "SourceSettingsError",
    "SourceStatus",
    "SourceViewer",
]


@pytest.mark.parametrize("name", ["source", "calendar_id", "editable", "type", "event_id"])
def test_source_occurrence_forbids_extra_fields(name):
    with pytest.raises(ValidationError):
        extension_types.SourceOccurrence(
            key="a", title="t", start=datetime(2026, 1, 1, tzinfo=UTC), **{name: "x"}
        )


def test_source_occurrence_timed_or_all_day():
    timed = extension_types.SourceOccurrence(
        key="a",
        title="t",
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert timed.all_day is False
    day = extension_types.SourceOccurrence(
        key="b", title="t", all_day=True, start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)
    )
    assert day.start is None


@pytest.mark.parametrize(
    "bad", [{"key": ""}, {"key": "a b"}, {"title": ""}, {"color": "red"}, {"status": "tentative"}]
)
def test_source_occurrence_field_shapes(bad):
    fields = {"key": "a", "title": "t", **bad}
    with pytest.raises(ValidationError):
        extension_types.SourceOccurrence(**fields)


def test_source_occurrence_is_frozen():
    item = extension_types.SourceOccurrence(key="a", title="t")
    with pytest.raises(ValidationError):
        item.title = "other"  # type: ignore[misc]


def test_no_extra_forbids_keys():
    with pytest.raises(ValidationError):
        extension_types.NoExtra.model_validate({"a": 1})


def test_settings_error_carries_loc():
    err = extension_types.SourceSettingsError(("mappings", 0, "field"), "bad")
    assert err.loc == ("mappings", 0, "field") and err.message == "bad"


def test_builtin_type_is_the_models_default():
    assert constants.BUILTIN_TYPE == DEFAULT_EVENT_TYPE


def test_contract_surface():
    expected = sorted(
        [*TYPES, "Registrar", "RegistryFrozenError", "ITEM_MAX_DAYS", "ITEM_TITLE_MAX"]
    )
    assert list(extensions.__all__) == expected
    for name in TYPES:
        assert getattr(extensions, name) is getattr(extension_types, name)
    assert extensions.Registrar and extensions.RegistryFrozenError
    assert extensions.ITEM_MAX_DAYS == 366 and extensions.ITEM_TITLE_MAX == 300
