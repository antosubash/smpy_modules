"""The payload compiler — model shape, the cache, and the read path.

Pure, no database. Per-type coercion lives in ``test_schema_types.py``; the
two contracts pinned here are the cache key that must include
``schema_version`` (§6.2) and the read path's refusal to raise on a record
written against an older schema (§8.3/§8.4).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sm_records.constants import ORPHANED_KEY
from sm_records.schema.compile import (
    PayloadValidationError,
    from_stored,
    get_model,
    to_jsonable,
    validate_payload,
)
from sm_records.schema.fields import validate_fields

from .schema_helpers import field, model_for, refuses


class TestRequiredAndDefaults:
    def test_a_required_field_must_be_present(self):
        with pytest.raises(PayloadValidationError) as exc:
            validate_payload(model_for(field("title", "text", required=True)), {})
        assert exc.value.errors[0]["field"] == "title"

    def test_a_required_field_refuses_an_explicit_null(self):
        refuses(field("title", "text", required=True), None)

    def test_a_required_relation_refuses_an_explicit_null(self):
        # `relation` compiles to `Any`, which pydantic would accept None for.
        definition = field("author", "relation", required=True, options={"target_type": "person"})
        refuses(definition, None)

    def test_an_optional_field_defaults_to_none(self):
        assert validate_payload(model_for(field("title", "text")), {}) == {"title": None}

    def test_an_optional_field_takes_its_declared_default(self):
        model = model_for(field("qty", "integer", default=7))
        assert validate_payload(model, {}) == {"qty": 7}

    def test_a_declared_default_is_coerced_not_stored_raw(self):
        model = model_for(field("price", "number", default="1.5"))
        assert validate_payload(model, {}) == {"price": Decimal("1.5")}


class TestModelShape:
    def test_an_unknown_payload_key_is_refused(self):
        with pytest.raises(PayloadValidationError) as exc:
            validate_payload(model_for(field("title", "text")), {"title": "x", "bogus": 1})
        assert exc.value.errors[0]["field"] == "bogus"

    def test_the_orphaned_key_is_allowed_and_preserved(self):
        model = model_for(field("title", "text"))
        out = validate_payload(model, {"title": "x", ORPHANED_KEY: {"price": "9"}})
        assert out[ORPHANED_KEY] == {"price": "9"}

    def test_the_orphaned_key_is_absent_when_not_supplied(self):
        assert ORPHANED_KEY not in validate_payload(model_for(field("title", "text")), {})

    def test_a_field_key_that_shadows_a_basemodel_attribute_still_works(self):
        # Field keys come from a web form; `json` and `copy` are attributes of
        # BaseModel, so every field is declared under an `f_` prefixed name.
        model = model_for(field("json", "text"), field("copy", "text"))
        assert validate_payload(model, {"json": "a", "copy": "b"}) == {"json": "a", "copy": "b"}

    def test_errors_name_every_failing_field(self):
        model = model_for(field("qty", "integer"), field("price", "number"))
        with pytest.raises(PayloadValidationError) as exc:
            validate_payload(model, {"qty": "x", "price": "y"})
        assert {item["field"] for item in exc.value.errors} == {"qty", "price"}


class TestModelCache:
    def test_same_type_and_version_returns_the_same_class(self):
        fields = validate_fields([field("title", "text")])
        first = get_model("cache_demo", 1, fields)
        assert get_model("cache_demo", 1, fields) is first

    def test_a_version_bump_returns_a_different_class(self):
        # Keyed on type_key alone, a schema edit would leave the old
        # validator serving writes against a shape that no longer exists.
        fields = validate_fields([field("title", "text")])
        first = get_model("cache_demo2", 1, fields)
        edited = validate_fields([field("title", "text"), field("qty", "integer")])
        second = get_model("cache_demo2", 2, edited)
        assert second is not first
        assert validate_payload(second, {"title": "x", "qty": 1})["qty"] == 1


class TestSerialisation:
    def test_to_jsonable_round_trips_decimal_date_and_datetime(self):
        definitions = [
            field("price", "number"),
            field("d", "date"),
            field("dt", "datetime"),
        ]
        model = model_for(*definitions)
        payload = {"price": "1.25", "d": "2026-09-19", "dt": "2026-09-19T12:00:00+00:00"}
        validated = validate_payload(model, payload)
        stored = to_jsonable(validated)
        assert stored == payload
        assert validate_payload(model, stored) == validated

    def test_to_jsonable_recurses_into_containers(self):
        data = {"a": [Decimal("1.5"), {"b": date(2026, 1, 1)}]}
        assert to_jsonable(data) == {"a": ["1.5", {"b": "2026-01-01"}]}


class TestFromStored:
    def test_a_missing_key_takes_the_default(self):
        fields = validate_fields([field("qty", "integer", default=3)])
        assert from_stored(fields, {}) == {"qty": 3}

    def test_an_unknown_key_is_dropped(self):
        fields = validate_fields([field("title", "text")])
        assert from_stored(fields, {"title": "x", "gone": "y"}) == {"title": "x"}

    def test_orphaned_values_survive(self):
        fields = validate_fields([field("title", "text")])
        out = from_stored(fields, {"title": "x", ORPHANED_KEY: {"price": "9"}})
        assert out[ORPHANED_KEY] == {"price": "9"}

    def test_a_value_that_will_not_coerce_is_left_as_is(self):
        # A row that 500s because someone tightened a constraint is what makes
        # people stop trusting the module — §8.3.
        fields = validate_fields([field("price", "number")])
        assert from_stored(fields, {"price": "not a number"}) == {"price": "not a number"}

    def test_a_coercible_value_written_under_an_older_type_is_coerced(self):
        # text -> number: the payload still holds the string, the read
        # coerces, and nothing was bulk-rewritten. Design §8.4.
        fields = validate_fields([field("price", "number")])
        assert from_stored(fields, {"price": "123"}) == {"price": Decimal("123")}


class TestCacheIsScopedByTypeId:
    def test_same_key_different_type_id_do_not_share_a_model(self) -> None:
        """Delete type ``product``, create a new ``product``: it is back at
        schema_version 1, and must not validate against the dead type's
        model. ``type_id`` is the part of the key that never recurs."""
        fields_a = validate_fields([{"key": "title", "type": "text", "label": "T"}])
        fields_b = validate_fields([{"key": "price", "type": "number", "label": "P"}])
        model_a = get_model("product", 1, fields_a, type_id=1)
        model_b = get_model("product", 1, fields_b, type_id=2)
        assert model_a is not model_b
        assert get_model("product", 1, fields_b, type_id=2) is model_b
        validate_payload(model_b, {"price": "1.5"})
        with pytest.raises(PayloadValidationError):
            validate_payload(model_b, {"title": "x"})
