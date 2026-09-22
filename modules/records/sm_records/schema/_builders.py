"""One pydantic annotation per field type, for the payload validator.

Split out of ``compile.py``, with the scalar coercers themselves split again
into ``_scalars.py`` for the 300-line cap. Everything here is an ``Annotated``
carrying ``BeforeValidator``/``AfterValidator`` callables
rather than a pydantic constraint object (``StringConstraints``,
``Field(ge=...)``). Two reasons, both load-bearing: an optional field's base is
a ``T | None`` union and pydantic cannot apply a constraint to a union; and
hand-written validators let every refusal carry a message written for the
person editing a record. Validators are therefore uniformly ``None``-tolerant,
and ``_reject_none`` is added back for required fields whose base is ``Any``
(``json``, ``relation``) — pydantic would otherwise accept a literal null.
``_text_check`` takes ``required`` for the same reason one rule on: a blank
string is not a value. ``select`` needs no equivalent (``""`` is not one of
its choices) and nor do ``email``/``url`` (their own checks refuse it).
"""

from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime as _datetime
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import AfterValidator, BeforeValidator

from sm_records.constants import TYPE_KEY_PATTERN
from sm_records.schema._scalars import (
    check_decimal,
    check_json_shape,
    to_bool,
    to_date,
    to_datetime,
    to_decimal,
    to_int,
)
from sm_records.schema.types import FieldType

MEDIA_MAX_LEN = 500
"""A ``media`` value is an opaque id or URL; the cap stops a payload smuggling
a base64 blob through a field the index never sees."""

# Deliberately not RFC 5322: `email-validator` is not a dependency and adding
# one for a single field type is not worth it. This catches the typo.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")
_TYPE_KEY_RE = re.compile(TYPE_KEY_PATTERN)
_UUID_RE = re.compile(r"^[0-9a-f]{32}$")
_URL_SCHEMES = ("http", "https")
_REF_KEYS = frozenset({"type", "uuid"})
_TEXTLIKE = (FieldType.TEXT, FieldType.LONGTEXT, FieldType.EMAIL, FieldType.URL)


def _reject_none(value: Any) -> Any:
    if value is None:
        raise ValueError("this field is required")
    return value


def _text_check(constraints: dict[str, Any], *, required: bool = False):
    minimum = constraints.get("min_length")
    maximum = constraints.get("max_length")
    pattern = re.compile(constraints["pattern"]) if constraints.get("pattern") else None

    def check(value: str | None) -> str | None:
        if value is None:
            return None
        # ``required`` alone means "present and not null", which left ``""``
        # satisfying a field the form marks with an asterisk.
        if required and not value.strip():
            raise ValueError("this field is required")
        if minimum is not None and len(value) < minimum:
            raise ValueError(f"must be at least {minimum} characters")
        if maximum is not None and len(value) > maximum:
            raise ValueError(f"must be at most {maximum} characters")
        if pattern is not None and not pattern.search(value):
            raise ValueError(f"must match {pattern.pattern}")
        return value

    return check


def _range_check(constraints: dict[str, Any], cast):
    low = cast(constraints["min"]) if constraints.get("min") is not None else None
    high = cast(constraints["max"]) if constraints.get("max") is not None else None

    def check(value: Any) -> Any:
        if value is None:
            return None
        if low is not None and value < low:
            raise ValueError(f"must be at least {low}")
        if high is not None and value > high:
            raise ValueError(f"must be at most {high}")
        return value

    return check


def _check_email(value: str | None) -> str | None:
    if value is not None and not _EMAIL_RE.match(value):
        raise ValueError("not a valid email address")
    return value


def _check_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in _URL_SCHEMES or not parsed.netloc:
        raise ValueError("must be an http:// or https:// URL with a host")
    return value


def _check_media(value: str | None) -> str | None:
    if value is not None and len(value) > MEDIA_MAX_LEN:
        raise ValueError(f"must be at most {MEDIA_MAX_LEN} characters")
    return value


def _select_check(options: dict[str, Any], *, many: bool):
    allowed = frozenset(choice["value"] for choice in options.get("choices", []))

    def check(value: Any) -> Any:
        if value is None:
            return None
        items = value if many else [value]
        if many and len(set(items)) != len(items):
            raise ValueError("contains duplicate values")
        unknown = [item for item in items if item not in allowed]
        if unknown:
            raise ValueError(f"not one of the configured choices: {unknown}")
        return value

    return check


def _check_json(value: Any) -> Any:
    """A ``json`` value has to be a container, and a *bounded* one.

    The shape bounds (:data:`~sm_records.schema._scalars.MAX_JSON_DEPTH`,
    :data:`~sm_records.schema._scalars.MAX_JSON_NODES`) are applied here and
    not only on the size of the serialised payload, because size is not what
    breaks: a 3 KB array nested three hundred deep is comfortably inside
    ``max_payload_bytes`` and is still a value pydantic's serializer refuses to
    render — which, once it is stored, is a 500 on every read of the type
    rather than a 422 on the one write that asked for it.
    """
    if value is None:
        return value
    if not isinstance(value, dict | list):
        raise ValueError("must be a JSON object or array, not a scalar")
    return check_json_shape(value)


def _check_ref(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected {'type': <type key>, 'uuid': <32 hex chars>}")
    unknown = sorted(set(value) - _REF_KEYS)
    if unknown:
        raise ValueError(f"unknown key(s) in relation value: {unknown}")
    target, uuid = value.get("type"), value.get("uuid")
    if not isinstance(target, str) or not _TYPE_KEY_RE.match(target):
        raise ValueError("'type' must be a record type key")
    if not isinstance(uuid, str) or not _UUID_RE.match(uuid):
        raise ValueError("'uuid' must be 32 hexadecimal characters")
    return {"type": target, "uuid": uuid}


def _check_ref_list(value: Any) -> Any:
    """A to-many relation, entry by entry — and **no ``null`` entries**.

    ``_check_ref`` is ``None``-tolerant because every validator here is (an
    optional field's value may be absent). Inside a list that tolerance means
    something else entirely: a hole. ``expanded[key]`` is rendered positionally
    against ``data[key]``, so a null in the middle of the list used to be
    accepted on write and then mislabel every entry after it. The position is
    named in the message, because a form showing five relation pickers has to
    say *which* one.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("expected a list of relation values")
    out = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(
                f"entry {index} is {'null' if item is None else 'not an object'}; "
                "every entry of a to-many relation must be "
                "{'type': <type key>, 'uuid': <32 hex chars>}"
            )
        out.append(_check_ref(item))
    return out


def _base_and_validators(
    field_type: FieldType, constraints: dict[str, Any], options: dict[str, Any], required: bool
) -> tuple[Any, list[Any]]:
    if field_type in _TEXTLIKE:
        extra = {FieldType.EMAIL: _check_email, FieldType.URL: _check_url}.get(field_type)
        return str, [_text_check(constraints, required=required), *([extra] if extra else [])]
    if field_type is FieldType.NUMBER:
        coerce = BeforeValidator(to_decimal)
        return Decimal, [coerce, check_decimal, _range_check(constraints, to_decimal)]
    if field_type is FieldType.INTEGER:
        return int, [BeforeValidator(to_int), _range_check(constraints, int)]
    if field_type is FieldType.BOOLEAN:
        return bool, [BeforeValidator(to_bool)]
    if field_type is FieldType.DATE:
        return _date, [BeforeValidator(to_date)]
    if field_type is FieldType.DATETIME:
        return _datetime, [BeforeValidator(to_datetime)]
    if field_type is FieldType.SELECT:
        return str, [_select_check(options, many=False)]
    if field_type is FieldType.MULTISELECT:
        return list[str], [_select_check(options, many=True)]
    if field_type is FieldType.MEDIA:
        return str, [_check_media]
    if field_type is FieldType.JSON:
        return Any, [_check_json]
    return Any, [_check_ref_list if options.get("many") else _check_ref]


def annotation_for(field: Any, *, required: bool) -> Any:
    """The pydantic annotation for one field's value.

    Duck-typed on purpose: it reads ``type``/``constraints``/``options`` off
    whatever it is handed, so ``compile.py`` never imports ``fields.py`` and
    the two stay free of a circular import.
    """
    field_type = FieldType(field.type)
    base, validators = _base_and_validators(
        field_type, dict(field.constraints or {}), dict(field.options or {}), required
    )
    if base is Any:
        if required:
            validators = [_reject_none, *validators]
    elif not required:
        base = base | None
    wrapped = [v if isinstance(v, BeforeValidator) else AfterValidator(v) for v in validators]
    return Annotated[(base, *wrapped)]
