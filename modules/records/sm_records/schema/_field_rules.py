"""The per-type rules for a field's ``options`` and ``constraints`` — split
from :mod:`sm_records.schema.fields` (which applies them and re-exports the
``on_delete`` names) for the 300-line cap."""

from __future__ import annotations

import re
from typing import Any

from sm_records._text import NUL_PROBLEM, has_nul
from sm_records.constants import TYPE_KEY_PATTERN
from sm_records.schema._keys import KEY_RE as _KEY_RE
from sm_records.schema._keys import FieldSchemaError
from sm_records.schema._keys import require as _require
from sm_records.schema.types import FieldType

__all__ = ["ON_DELETE_CHOICES", "ON_DELETE_DEFAULT", "validate_constraints", "validate_options"]

_TEXT_CONSTRAINTS = frozenset({"min_length", "max_length", "pattern"})
_NUMERIC_CONSTRAINTS = frozenset({"min", "max"})
_ALLOWED_CONSTRAINTS: dict[FieldType, frozenset[str]] = {
    FieldType.TEXT: _TEXT_CONSTRAINTS,
    FieldType.LONGTEXT: _TEXT_CONSTRAINTS,
    FieldType.EMAIL: _TEXT_CONSTRAINTS,
    FieldType.URL: _TEXT_CONSTRAINTS,
    FieldType.NUMBER: _NUMERIC_CONSTRAINTS,
    FieldType.INTEGER: _NUMERIC_CONSTRAINTS,
}

_CHOICE_TYPES = (FieldType.SELECT, FieldType.MULTISELECT)
_ALLOWED_OPTIONS: dict[FieldType, frozenset[str]] = {
    FieldType.SELECT: frozenset({"choices"}),
    FieldType.MULTISELECT: frozenset({"choices"}),
    FieldType.RELATION: frozenset({"target_type", "many", "on_delete"}),
}

ON_DELETE_CHOICES = frozenset({"restrict", "set_null", "cascade"})
ON_DELETE_DEFAULT = "restrict"
"""``restrict`` by default because a cascade default across a user-defined
graph deletes content nobody asked to delete. Design §9."""


def _validate_choices(key: str, options: dict[str, Any]) -> None:
    choices = options.get("choices")
    _require(isinstance(choices, list) and choices, key, "options.choices must be a non-empty list")
    seen: set[str] = set()
    for choice in choices:
        _require(isinstance(choice, dict), key, "each choice must be an object")
        value, label = choice.get("value"), choice.get("label")
        _require(isinstance(value, str) and value, key, "each choice needs a non-empty 'value'")
        _require(isinstance(label, str) and label, key, "each choice needs a non-empty 'label'")
        _require(not has_nul(value), key, f"choice value {NUL_PROBLEM}")
        _require(not has_nul(label), key, f"choice label {NUL_PROBLEM}")
        _require(value not in seen, key, f"duplicate choice value {value!r}")
        seen.add(str(value))


def _validate_relation(key: str, options: dict[str, Any]) -> None:
    target = options.get("target_type")
    _require(isinstance(target, str) and target, key, "options.target_type is required")
    _require(_KEY_RE.match(str(target)), key, f"options.target_type must match {TYPE_KEY_PATTERN}")
    _require(isinstance(options.get("many", False), bool), key, "options.many must be a boolean")
    on_delete = options.get("on_delete", ON_DELETE_DEFAULT)
    _require(
        on_delete in ON_DELETE_CHOICES,
        key,
        f"options.on_delete must be one of {sorted(ON_DELETE_CHOICES)}",
    )


def _only(key: str, what: str, field_type: FieldType, given: dict, allowed: frozenset) -> None:
    """Refuse any ``what`` (option, constraint) the field type does not take."""
    unknown = sorted(set(given) - allowed)
    _require(
        not unknown,
        key,
        f"unknown {what}(s) {unknown} for a {field_type.value} field"
        + (f"; allowed: {sorted(allowed)}" if allowed else " (it takes none)"),
    )


def validate_options(key: str, field_type: FieldType, options: dict[str, Any]) -> None:
    _only(key, "option", field_type, options, _ALLOWED_OPTIONS.get(field_type, frozenset()))
    if field_type in _CHOICE_TYPES:
        _validate_choices(key, options)
    elif field_type is FieldType.RELATION:
        _validate_relation(key, options)


def validate_constraints(key: str, field_type: FieldType, constraints: dict[str, Any]) -> None:
    allowed = _ALLOWED_CONSTRAINTS.get(field_type, frozenset())
    _only(key, "constraint", field_type, constraints, allowed)
    for name in ("min_length", "max_length"):
        value = constraints.get(name)
        if value is not None:
            _require(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                key,
                f"constraints.{name} must be a non-negative integer",
            )
    if constraints.get("pattern") is not None:
        pattern = constraints["pattern"]
        _require(isinstance(pattern, str), key, "constraints.pattern must be a string")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise FieldSchemaError(key, f"constraints.pattern is not a valid regex: {exc}") from exc
    for name in ("min", "max"):
        value = constraints.get(name)
        if value is not None:
            _require(
                isinstance(value, int | float) and not isinstance(value, bool),
                key,
                f"constraints.{name} must be a number",
            )
