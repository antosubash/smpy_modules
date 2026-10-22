"""A field key that collides with a column every record already has is refused.

Before the refusal such a key was accepted, indexed correctly, and then
filtered and sorted from ``records_record`` instead of from the index — a 200
with the wrong rows. The refusal happens on the screen that proposes the key.
"""

from __future__ import annotations

import pytest
from sm_records.index._fixed import RESERVED_FIELD_KEYS
from sm_records.index.query import FIXED_COLUMNS
from sm_records.models import Record
from sm_records.schema.fields import FieldSchemaError, validate_fields

from tests.app_harness import ADMIN, roles


def _field(key: str, type_: str, **overrides) -> dict:
    base = {"key": key, "type": type_, "label": key.title()}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# reserved field keys
# --------------------------------------------------------------------------


def test_reserved_keys_are_derived_from_the_model_and_the_fixed_columns():
    """The set is computed, not typed out, so a new ``Record`` column joins it
    on its own rather than becoming the next shadowed field key."""
    columns = {str(column.key) for column in Record.__table__.columns}
    assert columns <= RESERVED_FIELD_KEYS
    assert FIXED_COLUMNS <= RESERVED_FIELD_KEYS
    assert "_orphaned" in RESERVED_FIELD_KEYS
    # The names the QA probe filtered by and got the record column for.
    assert {"status", "slug", "position", "display_title", "published_at"} <= RESERVED_FIELD_KEYS


@pytest.mark.parametrize("key", sorted(RESERVED_FIELD_KEYS - {"_orphaned"}))
def test_validate_fields_refuses_every_reserved_key(key):
    with pytest.raises(FieldSchemaError) as excinfo:
        validate_fields([_field(key, "text")])
    assert excinfo.value.key == key
    assert "reserved" in excinfo.value.problem


def test_validate_fields_still_accepts_a_key_that_merely_looks_like_one():
    assert [f.key for f in validate_fields([_field("order_status", "text")])] == ["order_status"]


async def test_creating_a_type_with_a_shadowing_key_is_422(client):
    """The whole point of F1: the collision is refused on the screen that
    proposes it, rather than resolved silently at query time."""
    body = {
        "key": "shadow",
        "label": "Shadow",
        "fields": [_field("position", "integer", indexed=True)],
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "position"


async def test_a_type_with_no_shadowing_key_is_unaffected(client, field_def):
    body = {"key": "fine", "label": "Fine", "fields": [field_def("rank", "integer")]}
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201
