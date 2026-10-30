"""Schema edge cases (Task 22, fix round 3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.pipeline.ai.schema_safety import UnsafeSchema, check


def _code(prop) -> str:
    with pytest.raises(UnsafeSchema) as caught:
        check({"type": "object", "properties": {"a": prop}})
    return caught.value.code


@pytest.mark.parametrize("values", [{"enum": [2]}, {"const": 2}])
@pytest.mark.parametrize("combinator", ["anyOf", "oneOf", "allOf"])
def test_enum_or_const_beside_a_combinator_is_unsupported(values, combinator):
    """Ruling: that combination is not modelled (a Literal would bypass it)."""
    prop = {**values, combinator: [{"type": "integer", "minimum": 3}]}
    assert _code(prop) == "unsupported_schema"


@pytest.mark.parametrize("key", ["enum", "const"])
def test_an_integral_float_is_an_integer(key):
    value = [1.0, 2] if key == "enum" else 1.0
    model = check({"type": "object", "properties": {"a": {"type": "integer", key: value}}})
    got = model.model_validate({"a": 1})
    assert got.model_dump(by_alias=True) == {"a": 1}
    assert isinstance(got.model_dump(by_alias=True)["a"], int)


@pytest.mark.parametrize("key", ["enum", "const"])
def test_a_fractional_float_is_not_an_integer(key):
    value = [1.5] if key == "enum" else 1.5
    assert _code({"type": "integer", key: value}) == "invalid_schema"


def test_the_enum_still_restricts_the_values():
    model = check({"type": "object", "properties": {"a": {"type": "integer", "enum": [1.0]}}})
    with pytest.raises(ValidationError):
        model.model_validate({"a": 2})
