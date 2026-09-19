"""Compile a validated field list into a pydantic model for a record payload.

``pydantic.create_model`` rather than a ``jsonschema`` dependency: it adds
nothing to the install, gives coercion and per-field error paths for free, and
keeps the repo's pydantic/SQLModel convention. Design §6.2.

Two details that make this wrong if missed:

* **The cache key includes ``schema_version``.** Keyed on the type key alone,
  a schema edit leaves the old validator serving writes against a shape that
  no longer exists. :func:`get_model` refuses to offer that footgun — there is
  no single-argument form.
* **The cache is per process.** A schema edited in worker A is stale in worker
  B, so callers must key on the version *the type row they just read* reports,
  never on one cached alongside the model.

Every user field is declared under an internal name ``f_<key>`` with the key
itself as its alias. Without the prefix a field called ``json`` or ``copy``
would shadow an attribute of ``BaseModel`` and ``create_model`` would refuse
it — and a record type's field keys come from a web form, so that is a
runtime 500 waiting for its first admin. ``_orphaned`` is declared as
``ORPHANED`` for the same reason plus one more: pydantic treats a leading
underscore as a private attribute and will not accept it as a field name at
all. Dumps therefore always pass ``by_alias=True``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model
from pydantic import Field as PydField

from sm_records.constants import ORPHANED_KEY
from sm_records.schema._builders import annotation_for

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, see module docstring
    from sm_records.schema.fields import FieldDefinition

FIELD_PREFIX = "f_"
ORPHANED_FIELD = "ORPHANED"
"""Uppercase so no field key can collide with it: ``TYPE_KEY_PATTERN``
requires a lowercase first character."""

CACHE_MAX = 256
"""Bounded so a host churning through schema versions cannot grow the cache
without limit. Eviction is oldest-first, which for this access pattern means
the version nobody writes against any more."""

_MODEL_CACHE: dict[tuple[str, int], type[BaseModel]] = {}
_ADAPTER_CACHE: dict[tuple[str, bool, str, str], TypeAdapter[Any]] = {}


class PayloadValidationError(ValueError):
    """Raised by :func:`validate_payload`. ``errors`` is a flat list of
    ``{"field": key, "message": str}`` — the shape the API layer returns and
    the generic form renderer keys on."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        detail = "; ".join(f"{item['field']}: {item['message']}" for item in errors)
        super().__init__(detail or "payload validation failed")


def _cache_put(cache: dict[Any, Any], key: Any, value: Any) -> None:
    cache[key] = value
    while len(cache) > CACHE_MAX:
        cache.pop(next(iter(cache)))


def _public_name(loc: tuple[Any, ...]) -> str:
    """Map a pydantic error location back to the field key an editor sees."""
    if not loc:
        return "__root__"
    head = str(loc[0])
    if head == ORPHANED_FIELD:
        return ORPHANED_KEY
    if head.startswith(FIELD_PREFIX):
        head = head[len(FIELD_PREFIX) :]
    rest = "".join(f"[{part}]" for part in loc[1:])
    return f"{head}{rest}"


_VALUE_ERROR_PREFIX = "Value error, "


def _as_errors(exc: ValidationError) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for err in exc.errors():
        message = str(err.get("msg", "invalid value"))
        # Ours are raised as ValueError inside a validator; pydantic prefixes
        # those. The prefix is noise on a form field label.
        out.append(
            {
                "field": _public_name(err.get("loc", ())),
                "message": message.removeprefix(_VALUE_ERROR_PREFIX),
            }
        )
    return out


def build_model(
    type_key: str, schema_version: int, fields: list[FieldDefinition]
) -> type[BaseModel]:
    """Build (uncached) the payload model for one schema version."""
    definitions: dict[str, Any] = {}
    for field in fields:
        annotation = annotation_for(field, required=field.required)
        info = (
            PydField(alias=field.key)
            if field.required
            else PydField(default=field.default, alias=field.key)
        )
        definitions[f"{FIELD_PREFIX}{field.key}"] = (annotation, info)
    definitions[ORPHANED_FIELD] = (
        dict[str, Any] | None,
        PydField(default=None, alias=ORPHANED_KEY),
    )
    config = ConfigDict(
        # Unknown keys are refused rather than dropped: a typo'd key that is
        # silently discarded looks exactly like a field that failed to save.
        extra="forbid",
        populate_by_name=False,
        validate_default=True,
    )
    return create_model(f"Record_{type_key}_v{schema_version}", __config__=config, **definitions)


def clear_model_cache() -> None:
    """Drop every compiled model. For test harnesses whose in-memory
    databases restart primary keys at 1 on every test, so the same
    ``(type_id, type_key, schema_version)`` recurs with different fields —
    a situation a real database never produces."""
    _MODEL_CACHE.clear()


def get_model(
    type_key: str,
    schema_version: int,
    fields: list[FieldDefinition],
    *,
    type_id: int | None = None,
) -> type[BaseModel]:
    """Process-local cache of :func:`build_model`.

    Keyed on ``(type_id, type_key, schema_version)`` — never on the key or
    the version alone. ``schema_version`` is what a schema edit bumps; but a
    type can be deleted and a new one created under the *same key*, and the
    new one starts again at version 1. Keyed on the key, that new type would
    validate against the dead type's model. ``type_id`` is never reused, so
    it is the part of the key that survives that. Callers without a row
    (tests, the CLI) may omit it and get a key-scoped entry.
    """
    key = (type_id, type_key, schema_version)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    model = build_model(type_key, schema_version, fields)
    _cache_put(_MODEL_CACHE, key, model)
    return model


def validate_payload(model: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    """Validate a write payload and return the coerced values.

    Values come back in their Python types — ``Decimal`` stays ``Decimal``,
    a date stays a ``date``. Converting to strings here would mean every
    caller that wants to compute with a number has to parse it back, so the
    JSON-column serialisation is a separate, explicit step:
    :func:`to_jsonable`.
    """
    try:
        instance = model.model_validate(data)
    except ValidationError as exc:
        raise PayloadValidationError(_as_errors(exc)) from exc
    out = instance.model_dump(by_alias=True)
    if out.get(ORPHANED_KEY) is None:
        out.pop(ORPHANED_KEY, None)
    return out


def _adapter_for(field: FieldDefinition, required: bool) -> TypeAdapter[Any]:
    key = (
        str(getattr(field.type, "value", field.type)),
        required,
        json.dumps(field.constraints or {}, sort_keys=True, default=str),
        json.dumps(field.options or {}, sort_keys=True, default=str),
    )
    adapter = _ADAPTER_CACHE.get(key)
    if adapter is None:
        adapter = TypeAdapter(annotation_for(field, required=required))
        _cache_put(_ADAPTER_CACHE, key, adapter)
    return adapter


def coerce_value(field: FieldDefinition, value: Any, *, required: bool = False) -> Any:
    """Validate one value against one field definition.

    Lives here rather than in ``fields.py`` so that the field-definition
    validator can reuse the compiler for a field's ``default`` without
    ``compile.py`` ever importing ``fields.py``.
    """
    try:
        return _adapter_for(field, required).validate_python(value)
    except ValidationError as exc:
        errors = [{**item, "field": field.key} for item in _as_errors(exc)]
        raise PayloadValidationError(errors) from exc


def to_jsonable(data: Any) -> Any:
    """Convert a validated payload to types the JSON column can store.

    ``Decimal`` becomes a string, not a float: round-tripping through a float
    is exactly the precision loss the ``number`` contract (§7.3) exists to
    prevent, and it would put the payload and the index out of step.
    """
    if isinstance(data, Decimal):
        return str(data)
    if isinstance(data, datetime):
        return data.isoformat()
    if isinstance(data, date):
        return data.isoformat()
    if isinstance(data, dict):
        return {key: to_jsonable(value) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [to_jsonable(item) for item in data]
    return data


def from_stored(fields: list[FieldDefinition], data: dict[str, Any]) -> dict[str, Any]:
    """The read path: lenient coercion of a stored payload to the *current*
    schema. Design §8.3/§8.4.

    ``data`` is never bulk-rewritten, so a row stamped at schema version 3 is
    routinely read under version 5. Missing keys take the field's default,
    unknown keys are dropped (deleted fields survive under ``_orphaned``), and
    a value that will not coerce is handed back untouched rather than raising.
    That last rule is the one that matters: a record that vanishes — or
    500s — because someone tightened a constraint is what makes people stop
    trusting the module. It is marked invalid at a higher layer, not hidden.
    """
    out: dict[str, Any] = {}
    for field in fields:
        if field.key in data:
            try:
                out[field.key] = coerce_value(field, data[field.key])
            except (PayloadValidationError, ValueError):
                out[field.key] = data[field.key]
        else:
            out[field.key] = field.default
    orphaned = data.get(ORPHANED_KEY)
    if isinstance(orphaned, dict) and orphaned:
        out[ORPHANED_KEY] = orphaned
    return out
