"""Field definitions, and the rules a Record Type's ``fields`` list must obey.

This module is **pure**: it has no database access and never will. The one
check it cannot make is whether a ``relation``'s ``target_type`` names a type
that exists, which needs a query and therefore belongs to the services layer.
Everything that can be decided from the definitions alone is decided here, at
schema-save time, rather than discovered at write time — a combination that
cannot mean anything (``unique`` on a ``multiselect``, ``indexed`` on a
``longtext``) should be refused on the screen that proposes it.

A closed field-type set rather than raw JSON Schema: ``$ref`` makes a schema a
remote-fetch and cycle-resolution surface, a generic form renderer degrades to
a JSON textarea for anything non-trivial, and arbitrary schemas cannot be
diffed — which would make the schema-evolution classification of design §8
impossible. The escape hatch for genuinely unstructured data is the ``json``
field type, which is consequently not indexable and therefore not queryable.
"""

from __future__ import annotations

import re
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records._text import NUL_PROBLEM, has_nul
from sm_records.constants import MAX_LABEL_LEN, TYPE_KEY_PATTERN
from sm_records.schema._keys import KEY_RE as _KEY_RE
from sm_records.schema._keys import FieldSchemaError, validate_key
from sm_records.schema._keys import require as _require
from sm_records.schema.compile import PayloadValidationError, coerce_value
from sm_records.schema.types import NOT_UNIQUE, FieldType, indexable

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


class FieldDefinition(SQLModel):
    """One entry of ``RecordType.fields``.

    ``key`` is immutable once the field exists; ``label`` is freely editable.
    There is no rename operation, and that is deliberate: under design §8.2 a
    rename decomposes into "destructive then additive", which moves every
    value to ``_orphaned`` and leaves the new field empty — a rename that
    silently blanks a column of content. ``key`` is also a column in every
    index table, so a rename would have to be transactional across all of
    them. Add-new, migrate-values, delete-old is three operations the operator
    can see and abort between; it should not masquerade as an edit (§8.7).
    """

    key: str
    type: FieldType
    label: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any = None
    help: str | None = None
    constraints: dict[str, Any] = SQLField(default_factory=dict)
    options: dict[str, Any] = SQLField(default_factory=dict)


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


def _validate_options(key: str, field_type: FieldType, options: dict[str, Any]) -> None:
    _only(key, "option", field_type, options, _ALLOWED_OPTIONS.get(field_type, frozenset()))
    if field_type in _CHOICE_TYPES:
        _validate_choices(key, options)
    elif field_type is FieldType.RELATION:
        _validate_relation(key, options)


def _validate_constraints(key: str, field_type: FieldType, constraints: dict[str, Any]) -> None:
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


def _validate_flags(field: FieldDefinition) -> None:
    """``indexed`` and ``unique``, including the two normalisations.

    ``unique`` is enforced by a ``SELECT`` against the index table before the
    write (§7.8 — the index cannot carry a unique constraint, because every
    field of a kind shares one table). A unique field that is not indexed has
    nothing to select against, so ``unique`` is *normalised* to imply
    ``indexed`` rather than refused: the caller asked for something coherent
    and just left a checkbox unticked.

    A ``relation`` is forced on for the same shape of reason: §9's
    ``on_delete`` is enforced by ``_relations.referrers`` asking
    ``records_index_ref`` who points at a record — rows only indexed fields
    have — so an unindexed relation accepted all three behaviours and enforced
    none. It counts against the indexed ceiling like any other indexed field.
    """
    key = field.key
    if field.type is FieldType.RELATION:
        field.indexed = True
    if field.indexed or field.unique:
        _require(
            indexable(field.type),
            key,
            f"a {field.type.value} field cannot be indexed, so it is never queryable",
        )
    if field.unique:
        _require(
            field.type not in NOT_UNIQUE,
            key,
            f"unique is meaningless on a {field.type.value} field",
        )
        _require(
            not (field.type is FieldType.RELATION and field.options.get("many")),
            key,
            "unique is meaningless on a to-many relation",
        )
        field.indexed = True


def _validate_default(field: FieldDefinition) -> None:
    if field.default is None:
        return
    try:
        field.default = coerce_value(field, field.default, required=True)
    except PayloadValidationError as exc:
        detail = exc.errors[0]["message"] if exc.errors else str(exc)
        raise FieldSchemaError(field.key, f"default is invalid: {detail}") from exc


def validate_fields(raw: list[dict[str, Any]], *, on_save: bool = False) -> list[FieldDefinition]:
    """Validate and normalise a ``RecordType.fields`` list.

    ``on_save=True`` is the *proposal* path — a type create, update or
    rollback, which all reach this through ``services._schema.normalise``.
    The default is the *load* path (``services._payload.field_defs``, run on
    every read and write of a record), and it skips the one check that
    depends on runtime state outside the definition: see
    :func:`~sm_records.schema._keys.validate_key`.
    """
    _require(isinstance(raw, list), None, "fields must be a list")
    out: list[FieldDefinition] = []
    seen: set[str] = set()
    for entry in raw:
        _require(isinstance(entry, dict), None, "each field definition must be an object")
        key = validate_key(entry, seen, on_save=on_save)
        seen.add(key)

        raw_type = entry.get("type")
        try:
            field_type = FieldType(raw_type)
        except ValueError as exc:
            valid = sorted(member.value for member in FieldType)
            raise FieldSchemaError(key, f"unknown type {raw_type!r}; valid types: {valid}") from exc

        label = entry.get("label")
        _require(isinstance(label, str) and label.strip(), key, "label must be a non-empty string")
        _require(
            len(str(label)) <= MAX_LABEL_LEN,
            key,
            f"label must be at most {MAX_LABEL_LEN} characters",
        )
        # ``key`` is pattern-matched and cannot carry one; ``label``, ``help``
        # and the choice strings are free text, and every one of them is
        # stored in the type row's JSON ``fields`` column — which Postgres
        # refuses a NUL in exactly as it refuses one in ``text``.
        _require(not has_nul(label), key, f"label {NUL_PROBLEM}")
        _require(not has_nul(entry.get("help")), key, f"help {NUL_PROBLEM}")
        for flag in ("required", "unique", "indexed"):
            _require(isinstance(entry.get(flag, False), bool), key, f"{flag} must be true or false")
        options = entry.get("options") or {}
        constraints = entry.get("constraints") or {}
        _require(isinstance(options, dict), key, "options must be an object")
        _require(isinstance(constraints, dict), key, "constraints must be an object")

        _validate_options(key, field_type, options)
        _validate_constraints(key, field_type, constraints)

        field = FieldDefinition(
            key=key,
            type=field_type,
            label=str(label),
            required=bool(entry.get("required", False)),
            unique=bool(entry.get("unique", False)),
            indexed=bool(entry.get("indexed", False)),
            default=entry.get("default"),
            help=entry.get("help"),
            constraints=dict(constraints),
            options=dict(options),
        )
        if field_type is FieldType.RELATION:
            field.options.setdefault("many", False)
            field.options.setdefault("on_delete", ON_DELETE_DEFAULT)
        _validate_flags(field)
        _validate_default(field)
        out.append(field)
    return out
