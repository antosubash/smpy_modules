"""Builders shared by the two schema-compiler test modules.

Not a ``test_*`` module, so pytest does not collect it, and not a fixture in
``conftest.py``, because these tests are pure and must not acquire a
dependency on the database fixtures that live there.
"""

from __future__ import annotations

from typing import Any

import pytest
from sm_records.schema.compile import PayloadValidationError, build_model, validate_payload
from sm_records.schema.fields import validate_fields

CHOICES = {"choices": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]}
UUID_A = "a" * 32
UUID_B = "b" * 32


def field(key: str, field_type: str, **overrides: Any) -> dict[str, Any]:
    definition: dict[str, Any] = {"key": key, "type": field_type, "label": key.title()}
    definition.update(overrides)
    return definition


def model_for(*definitions: dict[str, Any], version: int = 1):
    """Build (uncached) a payload model from raw field definitions."""
    return build_model("product", version, validate_fields(list(definitions)))


def check(definition: dict[str, Any], value: Any) -> Any:
    """Validate a one-field payload and hand back the coerced value."""
    return validate_payload(model_for(definition), {definition["key"]: value})[definition["key"]]


def refuses(definition: dict[str, Any], value: Any) -> None:
    with pytest.raises(PayloadValidationError):
        validate_payload(model_for(definition), {definition["key"]: value})
