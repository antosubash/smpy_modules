"""A ``relation`` is always indexed, so its ``on_delete`` is always enforced.

``on_delete`` (design §9) is enforced by asking ``records_index_ref`` who
points at a record, and that table holds rows only for indexed fields, so an
unindexed ``relation`` used to accept ``restrict``/``set_null``/``cascade`` and
enforce none of them.

**No data migration goes with this.** The module was unreleased when it
landed: no installed host held an unindexed relation whose ref rows would have
to be backfilled.
"""

from __future__ import annotations

import pytest
from sm_records.index._fields import read_field
from sm_records.schema.fields import validate_fields
from sm_records.schema.types import FieldType
from sm_records.services._schema import normalise
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles


def _field(key: str, type_: str, **overrides) -> dict:
    base = {"key": key, "type": type_, "label": key.title()}
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# an unindexed relation cannot enforce ``on_delete``
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
