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

from typing import Any, Literal

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records._text import NUL_PROBLEM, has_nul
from sm_records.constants import MAX_LABEL_LEN

# ``ON_DELETE_*`` are re-exported: callers import them from here, as before
# the rules moved to ``_field_rules`` for the line cap.
from sm_records.schema._field_rules import ON_DELETE_CHOICES as ON_DELETE_CHOICES
from sm_records.schema._field_rules import ON_DELETE_DEFAULT as ON_DELETE_DEFAULT
from sm_records.schema._field_rules import validate_constraints, validate_options
from sm_records.schema._keys import FieldSchemaError, validate_key
from sm_records.schema._keys import require as _require
from sm_records.schema._text_checks import reading
from sm_records.schema.compile import PayloadValidationError, coerce_value
from sm_records.schema.types import NOT_UNIQUE, FieldType, indexable


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
    system: Literal["readonly", "internal"] | None = None
    """Set only on the ``sm_*`` fields a public-submissions type carries
    (``sm_records.public_submissions.spec``), which the server injects and
    writes. Last, and left out of the stored form when unset, so an ordinary
    field's stored dict is exactly what it was before the flag existed."""


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
        # Never a synchronous pattern match: a stored default was checked when
        # its schema was saved, and a proposed one is checked by the worker
        # (``services._patterns.check_defaults``) before it can be stored.
        with reading():
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

        validate_options(key, field_type, options)
        validate_constraints(key, field_type, constraints)
        system = entry.get("system")
        _require(system in (None, "readonly", "internal"), key, "system must be readonly/internal")

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
            system=system,
        )
        if field_type is FieldType.RELATION:
            field.options.setdefault("many", False)
            field.options.setdefault("on_delete", ON_DELETE_DEFAULT)
        _validate_flags(field)
        _validate_default(field)
        out.append(field)
    return out
