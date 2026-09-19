"""Regressions for the QA pass's F1 and F2 — the two silent-wrong-answer bugs.

F1: a field key that collides with a column every record already has was
accepted, indexed correctly, and then filtered and sorted from
``records_record`` instead of from the index — a 200 with the wrong rows.
F2: ``on_delete`` (design §9) is enforced by asking ``records_index_ref`` who
points at a record, and that table holds rows only for indexed fields, so an
unindexed ``relation`` accepted ``restrict``/``set_null``/``cascade`` and
enforced none of them.

**No data migration goes with either fix.** The module is unreleased: there is
no installed host holding a type with a field keyed ``status``, and none
holding an unindexed relation whose ref rows would have to be backfilled. The
seed's one such field was renamed (``order.status`` → ``order.order_status``)
in the same change.
"""

from __future__ import annotations

import pytest
from sm_records.constants import RESERVED_FIELD_KEYS
from sm_records.index._fields import read_field
from sm_records.index.query import FIXED_COLUMNS
from sm_records.models import Record
from sm_records.schema.fields import FieldSchemaError, validate_fields
from sm_records.schema.types import FieldType
from sm_records.services._schema import normalise
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles


def _field(key: str, type_: str, **overrides) -> dict:
    base = {"key": key, "type": type_, "label": key.title()}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# F1 — reserved field keys
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


# --------------------------------------------------------------------------
# F2 — an unindexed relation cannot enforce ``on_delete``
# --------------------------------------------------------------------------


def test_relation_is_normalised_to_indexed():
    defs = validate_fields(
        [_field("author", "relation", indexed=False, options={"target_type": "person"})]
    )
    assert defs[0].indexed is True
    assert defs[0].type is FieldType.RELATION


def test_a_stored_unindexed_relation_still_reads_as_indexed():
    """Normalising on *load* is not enough on its own: the index layer consumes
    the stored JSON, and a definition written before the normalisation existed
    would still leave ``records_index_ref`` empty."""
    stored = {
        "key": "author",
        "type": "relation",
        "label": "Author",
        "indexed": False,
        "options": {"target_type": "person", "many": False, "on_delete": "restrict"},
    }
    field = read_field(stored)
    assert field is not None
    assert field.key == "author"
    # An unindexed field of any other type is still not an index field.
    assert read_field({"key": "note", "type": "text", "indexed": False}) is None


def test_an_indexed_relation_counts_against_the_indexed_ceiling():
    """Normalised on means counted, or the ceiling would be a number the
    schema editor and the validator disagreed about."""
    settings = RecordsSettings(max_indexed_fields_per_type=0)
    with pytest.raises(Exception) as excinfo:
        normalise(
            [_field("author", "relation", indexed=False, options={"target_type": "person"})],
            settings,
        )
    assert "indexed fields exceeds the limit" in str(excinfo.value)


async def _relation_pair(client, on_delete: str) -> tuple[str, str]:
    """A ``person`` and a ``book`` pointing at it through an *unindexed*
    relation, as the QA probe declared it. Returns ``(person uuid, book uuid)``.
    """
    await client.post(
        "/api/records/types",
        json={"key": "person", "label": "Person", "fields": [_field("name", "text")]},
        headers=roles(ADMIN),
    )
    await client.post(
        "/api/records/types",
        json={
            "key": "book",
            "label": "Book",
            "fields": [
                _field("t", "text"),
                _field(
                    "author",
                    "relation",
                    indexed=False,
                    options={"target_type": "person", "on_delete": on_delete},
                ),
            ],
        },
        headers=roles(ADMIN),
    )
    ann = await client.post(
        "/api/records/types/person/records",
        json={"data": {"name": "Ann"}},
        headers=roles(ADMIN),
    )
    ann_uuid = ann.json()["uuid"]
    book = await client.post(
        "/api/records/types/book/records",
        json={"data": {"t": "B1", "author": {"type": "person", "uuid": ann_uuid}}},
        headers=roles(ADMIN),
    )
    return ann_uuid, book.json()["uuid"]


async def test_restrict_blocks_a_delete_through_an_unindexed_relation(client):
    ann, book = await _relation_pair(client, "restrict")
    resp = await client.delete(f"/api/records/types/person/records/{ann}", headers=roles(ADMIN))
    assert resp.status_code == 409
    assert resp.json()["referrers"] == [book]


async def test_set_null_clears_the_reference_on_an_unindexed_relation(client):
    ann, book = await _relation_pair(client, "set_null")
    resp = await client.delete(f"/api/records/types/person/records/{ann}", headers=roles(ADMIN))
    assert resp.status_code == 204
    read = await client.get(f"/api/records/types/book/records/{book}", headers=roles(ADMIN))
    assert read.json()["data"]["author"] is None


async def test_cascade_trashes_the_dependent_on_an_unindexed_relation(client):
    ann, book = await _relation_pair(client, "cascade")
    resp = await client.delete(f"/api/records/types/person/records/{ann}", headers=roles(ADMIN))
    assert resp.status_code == 204
    read = await client.get(f"/api/records/types/book/records/{book}", headers=roles(ADMIN))
    assert read.status_code == 404


async def test_a_relation_saved_as_unindexed_reads_back_indexed(client):
    """The stored definition is the normalised one, so the schema editor and
    every later diff see ``indexed: true`` rather than what was sent."""
    await client.post(
        "/api/records/types",
        json={"key": "person", "label": "Person", "fields": [_field("name", "text")]},
        headers=roles(ADMIN),
    )
    created = await client.post(
        "/api/records/types",
        json={
            "key": "book",
            "label": "Book",
            "fields": [
                _field("author", "relation", indexed=False, options={"target_type": "person"})
            ],
        },
        headers=roles(ADMIN),
    )
    assert created.status_code == 201
    assert created.json()["fields"][0]["indexed"] is True
