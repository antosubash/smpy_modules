"""Event types: validating ``extra``, what a public page may see of it, and a type's description.

``extra`` is the type's own data, validated against its ``extra_model`` on every write, capped
at ``EXTRA_MAX_BYTES`` and stored as the model's JSON dump. An event whose type is not installed
here keeps its ``extra`` untouched: nothing in this module (or any write path) validates, drops
or rewrites it, and only a type's ``public_fields`` ever reach a public surface.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from sm_events.calendar import registry
from sm_events.calendar.extension_types import EventType
from sm_events.core import constants
from sm_events.core.errors import UnknownType
from sm_events.core.errors_extensions import ExtraTooLarge
from sm_events.web.schemas.extensions import TypeOut

__all__ = ["public_extra", "type_info", "validate_extra"]

_BODY = ("body", "extra")


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str).encode())


def type_info(etype: EventType) -> TypeOut:
    """A type as the API lists it: its schema and the defaults of its optional fields."""
    model = etype.extra_model
    blank = model.model_construct()
    defaults = {
        name: to_jsonable_python(getattr(blank, name))
        for name, field in model.model_fields.items()
        if not field.is_required()
    }
    return TypeOut(
        id=etype.id,
        label_key=etype.label_key,
        icon=etype.icon,
        builtin=etype.id == constants.BUILTIN_TYPE,
        public_fields=sorted(etype.public_fields),
        json_schema=model.model_json_schema(),
        defaults=defaults,
    )


def validate_extra(type_id: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    """``extra`` as the type stores it. Raises :class:`UnknownType` for a type that is not
    installed, :class:`ExtraTooLarge`, or a ``RequestValidationError`` locating each problem
    under ``body.extra`` (unknown keys included: the model forbids them)."""
    etype = registry.get_type(type_id)
    if etype is None:
        raise UnknownType
    if _size(extra) > constants.EXTRA_MAX_BYTES:
        raise ExtraTooLarge
    try:
        model = etype.extra_model.model_validate(dict(extra))
    except ValidationError as exc:
        # ``input`` is left out: a value is never echoed back.
        raise RequestValidationError(
            [{"loc": (*_BODY, *e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        ) from None
    dumped = model.model_dump(mode="json")
    if _size(dumped) > constants.EXTRA_MAX_BYTES:
        raise ExtraTooLarge
    return dumped


def public_extra(type_id: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    """The part of ``extra`` a public page may carry: the type's ``public_fields``, and only
    when the type is installed (an unknown type's data is never published)."""
    etype = registry.get_type(type_id)
    if etype is None:
        return {}
    return {k: extra[k] for k in sorted(etype.public_fields) if k in extra}
