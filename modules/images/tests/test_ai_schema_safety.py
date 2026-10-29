"""A prompt's ``output_schema`` is user input: bounded, local, then a model.

``schema_safety.check`` caps depth, properties, ``$ref`` count and pattern
length, refuses remote references and the keywords the model builder does not
understand, and only then is a pydantic model built from it (cached per
prompt id and revision).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sm_images.ai import schema_safety
from sm_images.ai.schema_safety import UnsafeSchema, check, output_model

PERSON = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "maxLength": 50},
        "count": {"type": "integer", "minimum": 0},
        "pattern": {"type": "string"},  # a *property* called pattern is data
        "kind": {"enum": ["a", "b"]},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "where": {"$ref": "#/$defs/Place"},
        "note": {"type": ["string", "null"]},
    },
    "required": ["label", "count"],
    "additionalProperties": False,
    "$defs": {"Place": {"type": "object", "properties": {"name": {"type": "string"}}}},
}


def _nested(depth: int) -> dict:
    node: dict = {"type": "string"}
    for _ in range(depth):
        node = {"type": "object", "properties": {"x": node}}
    return node


def _code(schema) -> str:
    with pytest.raises(UnsafeSchema) as caught:
        check(schema)
    return caught.value.code


def test_schema_safety_rejects_deep_schema():
    assert _code(_nested(schema_safety.MAX_DEPTH + 2)) == "too_deep"
    check(_nested(schema_safety.MAX_DEPTH - 1))


def test_too_many_properties():
    props = {f"p{i}": {"type": "string"} for i in range(schema_safety.MAX_PROPERTIES + 1)}
    assert _code({"type": "object", "properties": props}) == "too_many_properties"


@pytest.mark.parametrize(
    "ref", ["https://evil.example/s.json", "file:///etc/passwd", "other.json#/x", "#/properties/a"]
)
def test_remote_and_non_definition_refs_are_refused(ref):
    assert _code({"type": "object", "properties": {"a": {"$ref": ref}}}) == "remote_ref"


def test_recursive_ref_is_refused():
    schema = {
        "type": "object",
        "properties": {"n": {"$ref": "#/$defs/N"}},
        "$defs": {"N": {"type": "object", "properties": {"next": {"$ref": "#/$defs/N"}}}},
    }
    assert _code(schema) == "recursive_ref"


def test_too_many_refs():
    props = {f"p{i}": {"$ref": "#/$defs/S"} for i in range(schema_safety.MAX_REFS + 1)}
    schema = {"type": "object", "properties": props, "$defs": {"S": {"type": "string"}}}
    assert _code(schema) == "too_many_refs"


def test_long_pattern_is_refused():
    long = "a" * (schema_safety.MAX_PATTERN + 1)
    assert _code({"type": "object", "properties": {"a": {"type": "string", "pattern": long}}}) == (
        "pattern_too_long"
    )


@pytest.mark.parametrize("keyword", ["patternProperties", "allOf", "not", "if", "$dynamicRef"])
def test_unsupported_keywords_are_refused(keyword):
    schema = {"type": "object", "properties": {"a": {"type": "string", keyword: {}}}}
    assert _code(schema) == "unsupported_schema"


@pytest.mark.parametrize("root", [{"type": "string"}, [], "x", {"type": "array"}])
def test_the_root_must_be_an_object(root):
    assert _code(root) == "not_an_object"


def test_a_safe_schema_becomes_a_validating_model():
    model = output_model(PERSON)
    ok = model.model_validate({"label": "cow", "count": 2, "pattern": "x", "where": {"name": "f"}})
    dumped = ok.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped == {"label": "cow", "count": 2, "pattern": "x", "where": {"name": "f"}}
    for bad in ({"label": "x"}, {"label": "x", "count": -1}, {"label": "x", "count": 1, "z": 1}):
        with pytest.raises(ValidationError):
            model.model_validate(bad)
    with pytest.raises(ValidationError):
        model.model_validate({"label": "x", "count": 1, "kind": "c"})


def test_models_are_cached_per_prompt_revision():
    a = output_model(PERSON, key=("p1", 1))
    assert output_model(PERSON, key=("p1", 1)) is a
    assert output_model(PERSON, key=("p1", 2)) is not a


def test_an_invalid_pattern_is_refused_at_check_time():
    schema = {"type": "object", "properties": {"a": {"type": "string", "pattern": "(a"}}}
    assert _code(schema) == "invalid_schema"


# --- review fixes (Task 22, round 1) ---


def test_depth_boundary():
    check(_nested(schema_safety.MAX_DEPTH))
    assert _code(_nested(schema_safety.MAX_DEPTH + 1)) == "too_deep"


def test_a_700_deep_items_chain_is_too_deep_not_a_crash():
    node: dict = {"type": "string"}
    for _ in range(700):
        node = {"type": "array", "items": node}
    assert _code({"type": "object", "properties": {"a": node}}) == "too_deep"


def test_a_deep_unreferenced_definition_is_too_deep():
    deep = _nested(schema_safety.MAX_DEPTH + 3)
    assert _code({"type": "object", "properties": {}, "$defs": {"D": deep}}) == "too_deep"


@pytest.mark.parametrize(
    "prop",
    [
        {"$ref": "#/$defs/S", "type": "string"},  # $ref beside structure
        {"type": "string", "format": "date-time"},  # a semantic the model would not enforce
    ],
)
def test_what_the_model_would_not_honour_is_refused(prop):
    schema = {"type": "object", "properties": {"a": prop}, "$defs": {"S": {"type": "string"}}}
    assert _code(schema) == "unsupported_schema"


def test_required_names_must_be_properties():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]}
    assert _code(schema) == "unsupported_schema"


def test_an_optional_field_is_not_nullable_unless_it_says_so():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": ["string", "null"]}},
    }
    model = output_model(schema)
    model.model_validate({})  # omitted is fine
    model.model_validate({"b": None})  # nullable
    with pytest.raises(ValidationError):
        model.model_validate({"a": None})


@pytest.mark.parametrize("extra", [True, None])
def test_additional_properties_are_kept_unless_forbidden(extra):
    schema: dict = {"type": "object", "properties": {"a": {"type": "string"}}}
    if extra is not None:
        schema["additionalProperties"] = extra
    got = output_model(schema).model_validate({"a": "x", "z": 1})
    assert got.model_dump(by_alias=True, exclude_unset=True) == {"a": "x", "z": 1}


def test_defs_and_definitions_are_separate_namespaces():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/S"}},
        "$defs": {"S": {"type": "string"}},
    }
    assert _code(schema) == "invalid_schema"
    both = {
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/S"}, "b": {"$ref": "#/$defs/S"}},
        "definitions": {"S": {"type": "string"}},
        "$defs": {"S": {"type": "integer"}},
    }
    ok = output_model(both).model_validate({"a": "x", "b": 1})
    assert ok.model_dump(by_alias=True) == {"a": "x", "b": 1}


def test_check_returns_the_model_it_built():
    model = check(PERSON)
    assert model.model_validate({"label": "x", "count": 1})
