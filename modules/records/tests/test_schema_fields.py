"""Field-definition validation — pure, no database.

The rule this file exists to pin down: a combination that cannot mean anything
is refused at schema-save time, on the screen that proposes it, rather than
discovered at record-write time by whoever happens to trip it first.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.constants import MAX_KEY_LEN, ORPHANED_KEY
from sm_records.schema.fields import (
    FieldSchemaError,
    fields_by_key,
    validate_fields,
)
from sm_records.schema.types import FieldType


def text(key: str = "title", **overrides):
    field = {"key": key, "type": "text", "label": "Title"}
    field.update(overrides)
    return field


def choices(*values):
    return {"choices": [{"value": value, "label": value.upper()} for value in values]}


class TestKeys:
    def test_accepts_a_minimal_definition(self):
        [field] = validate_fields([text()])
        assert field.key == "title"
        assert field.type is FieldType.TEXT
        assert field.required is False
        assert field.constraints == {}

    @pytest.mark.parametrize("key", ["Title", "1title", "with-dash", "with space", ""])
    def test_refuses_a_key_that_is_not_an_identifier(self, key):
        with pytest.raises(FieldSchemaError):
            validate_fields([text(key)])

    def test_refuses_an_overlong_key(self):
        with pytest.raises(FieldSchemaError, match="at most"):
            validate_fields([text("a" * (MAX_KEY_LEN + 1))])

    def test_refuses_the_reserved_orphaned_key(self):
        with pytest.raises(FieldSchemaError, match="reserved"):
            validate_fields([text(ORPHANED_KEY)])

    def test_refuses_a_duplicate_key(self):
        with pytest.raises(FieldSchemaError, match="duplicate"):
            validate_fields([text(), text()])

    def test_error_names_the_offending_key(self):
        with pytest.raises(FieldSchemaError) as exc:
            validate_fields([text("body", type="longtext", indexed=True)])
        assert "body" in str(exc.value)
        assert exc.value.key == "body"

    def test_refuses_an_unknown_type(self):
        with pytest.raises(FieldSchemaError, match="unknown type"):
            validate_fields([text(type="colour")])

    def test_refuses_a_blank_label(self):
        with pytest.raises(FieldSchemaError, match="label"):
            validate_fields([text(label="  ")])


class TestIndexedAndUnique:
    @pytest.mark.parametrize("field_type", ["longtext", "json", "media"])
    def test_refuses_indexed_on_an_unindexable_type(self, field_type):
        with pytest.raises(FieldSchemaError, match="cannot be indexed"):
            validate_fields([text("f", type=field_type, indexed=True)])

    def test_allows_indexed_on_an_indexable_type(self):
        [field] = validate_fields([text(indexed=True)])
        assert field.indexed is True

    def test_refuses_unique_on_multiselect(self):
        definition = text("tags", type="multiselect", unique=True, options=choices("a"))
        with pytest.raises(FieldSchemaError, match="unique"):
            validate_fields([definition])

    def test_refuses_unique_on_a_to_many_relation(self):
        definition = text(
            "eds",
            type="relation",
            unique=True,
            options={"target_type": "person", "many": True},
        )
        with pytest.raises(FieldSchemaError, match="to-many"):
            validate_fields([definition])

    def test_allows_unique_on_a_to_one_relation(self):
        definition = text("author", type="relation", unique=True, options={"target_type": "person"})
        [field] = validate_fields([definition])
        assert field.unique is True and field.indexed is True

    def test_unique_normalises_indexed_rather_than_refusing(self):
        # Nothing to SELECT against otherwise — design §7.8.
        [field] = validate_fields([text(unique=True)])
        assert field.indexed is True


class TestOptions:
    def test_select_requires_choices(self):
        with pytest.raises(FieldSchemaError, match="choices"):
            validate_fields([text("cat", type="select")])

    def test_select_refuses_duplicate_choice_values(self):
        definition = text("cat", type="select", options=choices("a", "a"))
        with pytest.raises(FieldSchemaError, match="duplicate choice"):
            validate_fields([definition])

    def test_select_refuses_an_empty_choice_value(self):
        options = {"choices": [{"value": "", "label": "Blank"}]}
        with pytest.raises(FieldSchemaError, match="value"):
            validate_fields([text("cat", type="select", options=options)])

    def test_relation_requires_a_target_type(self):
        with pytest.raises(FieldSchemaError, match="target_type"):
            validate_fields([text("author", type="relation", options={})])

    def test_relation_refuses_a_malformed_target_type(self):
        definition = text("author", type="relation", options={"target_type": "Person"})
        with pytest.raises(FieldSchemaError, match="target_type"):
            validate_fields([definition])

    def test_relation_defaults_many_and_on_delete(self):
        definition = text("author", type="relation", options={"target_type": "person"})
        [field] = validate_fields([definition])
        assert field.options == {"target_type": "person", "many": False, "on_delete": "restrict"}

    def test_relation_refuses_an_unknown_on_delete(self):
        options = {"target_type": "person", "on_delete": "explode"}
        with pytest.raises(FieldSchemaError, match="on_delete"):
            validate_fields([text("author", type="relation", options=options)])

    def test_refuses_options_on_a_type_that_takes_none(self):
        with pytest.raises(FieldSchemaError, match="unknown option"):
            validate_fields([text(options={"choices": []})])

    def test_refuses_an_unknown_option_key(self):
        options = {"target_type": "person", "sort": "asc"}
        with pytest.raises(FieldSchemaError, match="unknown option"):
            validate_fields([text("author", type="relation", options=options)])


class TestConstraints:
    def test_text_accepts_its_three_constraints(self):
        constraints = {"min_length": 1, "max_length": 5, "pattern": "^[a-z]+$"}
        [field] = validate_fields([text(constraints=constraints)])
        assert field.constraints == constraints

    def test_number_accepts_min_and_max(self):
        [field] = validate_fields([text("p", type="number", constraints={"min": 0, "max": 9})])
        assert field.constraints == {"min": 0, "max": 9}

    def test_refuses_a_numeric_constraint_on_text(self):
        with pytest.raises(FieldSchemaError, match="unknown constraint"):
            validate_fields([text(constraints={"min": 1})])

    def test_refuses_a_text_constraint_on_number(self):
        with pytest.raises(FieldSchemaError, match="unknown constraint"):
            validate_fields([text("p", type="number", constraints={"max_length": 3})])

    def test_refuses_any_constraint_on_boolean(self):
        with pytest.raises(FieldSchemaError, match="takes none"):
            validate_fields([text("live", type="boolean", constraints={"min": 0})])

    def test_refuses_an_uncompilable_pattern(self):
        with pytest.raises(FieldSchemaError, match="regex"):
            validate_fields([text(constraints={"pattern": "([a-z"})])

    def test_refuses_a_negative_length(self):
        with pytest.raises(FieldSchemaError, match="min_length"):
            validate_fields([text(constraints={"min_length": -1})])


class TestDefaults:
    def test_default_is_coerced_to_the_field_type(self):
        [field] = validate_fields([text("p", type="number", default="12.5")])
        assert field.default == Decimal("12.5")

    def test_default_must_satisfy_the_field_type(self):
        with pytest.raises(FieldSchemaError, match="default is invalid"):
            validate_fields([text("p", type="number", default="abc")])

    def test_default_must_satisfy_the_constraints(self):
        with pytest.raises(FieldSchemaError, match="default is invalid"):
            validate_fields([text(default="toolong", constraints={"max_length": 3})])

    def test_default_must_be_a_configured_choice(self):
        definition = text("cat", type="select", default="z", options=choices("a"))
        with pytest.raises(FieldSchemaError, match="default is invalid"):
            validate_fields([definition])

    def test_a_number_default_with_six_decimal_places_is_refused(self):
        with pytest.raises(FieldSchemaError, match="default is invalid"):
            validate_fields([text("p", type="number", default="1.234567")])


def test_fields_by_key_indexes_the_list():
    fields = validate_fields([text(), text("body", type="longtext", label="Body")])
    by_key = fields_by_key(fields)
    assert set(by_key) == {"title", "body"}
    assert by_key["body"].type is FieldType.LONGTEXT


def test_validate_fields_accepts_an_empty_list():
    assert validate_fields([]) == []
