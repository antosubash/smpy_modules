"""The suggested and the validated column mapping (R9)."""

from __future__ import annotations

import pytest
from sm_newsletter.core.errors_import import ImportBadMapping
from sm_newsletter.imports.mapping import suggest, validate
from sm_records.contracts.newsletter_import import ImportField, ImportTargets


def _targets(tags: str = "present", *keys: str) -> ImportTargets:
    fields = [
        ImportField(key=k, label=k, type="text")
        for k in (keys or ("first_name", "last_name", "city"))
    ]
    return ImportTargets(fields=fields, tags=tags)


def _cols(*headers: str) -> list[dict]:
    return [{"key": h.casefold(), "header": h} for h in headers]


FOUND = [{"label": "VIP", "value": "vip", "count": 2}]


def test_suggest_names_and_tags():
    got = suggest(_cols("First Name", "Last Name", "City"), _targets(), FOUND)
    assert got == {"fields": {"0": "first_name", "1": "last_name"}, "tags": True}


def test_suggest_german_names():
    got = suggest(_cols("Vorname", "Nachname"), _targets(), [])
    assert got == {"fields": {"0": "first_name", "1": "last_name"}, "tags": False}


def test_suggest_without_the_fields_or_tags():
    got = suggest(_cols("First Name"), _targets("missing", "city"), FOUND)
    assert got == {"fields": {}, "tags": False}
    assert suggest(_cols("A"), _targets("creatable"), FOUND)["tags"] is True


def test_suggest_each_field_once():
    got = suggest(_cols("First Name", "Vorname"), _targets(), [])
    assert got["fields"] == {"0": "first_name"}


def test_validate_accepts_and_normalises():
    cols = _cols("A", "B")
    ok = validate(
        {"fields": {"1": "city"}, "tags": True}, columns=cols, targets=_targets(), tags_found=FOUND
    )
    assert ok == {"fields": {"1": "city"}, "tags": True}
    assert validate({}, columns=cols, targets=_targets(), tags_found=[]) == {
        "fields": {},
        "tags": False,
    }


@pytest.mark.parametrize(
    ("raw", "detail", "tags"),
    [
        ({"fields": {"7": "city"}}, "fields.7", "present"),
        ({"fields": {"x": "city"}}, "fields.x", "present"),
        ({"fields": {"0": "nope"}}, "fields.0", "present"),
        ({"fields": {"0": "city", "1": "city"}}, "fields.1", "present"),
        ({"fields": {"0": 5}}, "fields.0", "present"),
        ({"fields": {"0": "city", "00": "first_name"}}, "fields.00", "present"),
        ({"fields": {"+1": "city"}}, "fields.+1", "present"),
        ({"fields": {" 1": "city"}}, "fields. 1", "present"),
        ({"fields": {"-1": "city"}}, "fields.-1", "present"),
        ({"fields": []}, "fields", "present"),
        ({"fields": {}, "tags": True}, "tags", "missing"),
        ({"tags": "yes"}, "tags", "present"),
        ([], "mapping", "present"),
        ("x", "mapping", "present"),
    ],
)
def test_validate_refusals(raw, detail, tags):
    with pytest.raises(ImportBadMapping) as err:
        validate(raw, columns=_cols("A", "B"), targets=_targets(tags), tags_found=FOUND)
    assert detail in str(err.value)
    assert "nope" not in str(err.value).replace("fields.0", "")


def test_validate_canonicalises_column_indices():
    cols = _cols(*(f"c{i}" for i in range(9)))
    got = validate(
        {"fields": {"007": "city", "00": "first_name"}},
        columns=cols,
        targets=_targets(),
        tags_found=[],
    )
    assert got["fields"] == {"7": "city", "0": "first_name"}
