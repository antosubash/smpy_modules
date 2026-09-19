"""Deleted values, and getting them back. Design doc §8.3, §8.8 — and the
record-revision restore of §16 that shares their "validate against the schema
as it is now" rule.

The invariant under all of it: **no bulk rewrite**. Deleting a field leaves
every record's payload exactly as it was; the value moves under ``_orphaned``
on that record's own next write, and until then it simply sits there, ignored
on read. The only bulk write in the whole of §8 is an explicit ``discard``.
"""

from __future__ import annotations

import pytest
from sm_records.constants import ORPHANED_KEY
from sm_records.models import IndexText, RevisionEvent
from sm_records.services import records as record_service
from sm_records.services import revisions as revision_service
from sm_records.services import schema_change
from sm_records.services import types as type_service
from sm_records.services._common import type_resolver
from sm_records.services.errors import NotFound, OrphanedKeyConflict, ValidationFailed
from sm_records.settings import RecordsSettings
from sqlalchemy import select


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


@pytest.fixture
def fields(field_def):
    return [field_def("title", "text"), field_def("price", "text")]


@pytest.fixture
async def product(db, settings, fields):
    return await type_service.create_type(
        db, key="product", label="Product", fields_raw=fields, settings=settings
    )


async def drop_price(db, settings, rtype, fields, *, version: int = 1, **kwargs):
    return await schema_change.apply(
        db, rtype, fields_raw=[fields[0]], expected_version=version, settings=settings, **kwargs
    )


async def test_a_removed_fields_value_stays_in_the_payload_untouched(db, settings, product, fields):
    record = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    updated, diff = await drop_price(db, settings, product, fields)

    assert diff.kind.value == "destructive"
    # Not rewritten, not moved, not deleted — the record was not touched.
    assert record.data == {"title": "One", "price": "12"}
    # But it is not part of the shape any more, so it does not read back.
    assert "price" not in record_service.read_view(updated, record)["data"]


async def test_the_next_write_moves_it_under_orphaned(db, settings, product, fields):
    """The lazy destructive migration of §8.3: one record at a time, on edit,
    never in a job that can half-fail."""
    record = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    updated, _ = await drop_price(db, settings, product, fields)

    await record_service.update_record(
        db, updated, record, expected_version=1, data={"title": "Renamed"}, settings=settings
    )
    assert record.data == {"title": "Renamed", ORPHANED_KEY: {"price": "12"}}


async def test_a_client_can_never_write_orphaned_itself(db, settings, product):
    record = await record_service.create_record(
        db, product, data={"title": "One"}, settings=settings
    )
    with pytest.raises(ValidationFailed, match="reserved"):
        await record_service.update_record(
            db,
            product,
            record,
            expected_version=1,
            data={"title": "One", ORPHANED_KEY: {"price": "9"}},
            settings=settings,
        )


async def test_re_adding_the_key_is_refused_until_the_caller_chooses(db, settings, product, fields):
    """§8.8: restoring silently makes deleted content reappear, shadowing makes
    it permanently unreachable, so neither happens without being asked for."""
    migrated = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    await record_service.create_record(
        db, product, data={"title": "Two", "price": "34"}, settings=settings
    )
    updated, _ = await drop_price(db, settings, product, fields)
    # One record has been written since the delete, so its value sits under
    # ``_orphaned``; the other still carries it top-level, unmigrated. Both
    # count — the operator's decision is about the values, not the shape.
    await record_service.update_record(
        db, updated, migrated, expected_version=1, data={"title": "One"}, settings=settings
    )
    await record_service.create_record(db, updated, data={"title": "Three"}, settings=settings)

    with pytest.raises(OrphanedKeyConflict) as excinfo:
        await schema_change.apply(
            db, updated, fields_raw=fields, expected_version=2, settings=settings
        )
    assert excinfo.value.conflicts == {"price": 2}
    assert [f["key"] for f in updated.fields] == ["title"]


async def test_restore_brings_the_value_back_on_read_and_into_the_index(
    db, settings, product, fields
):
    """Restore writes nothing: the read path falls back to ``_orphaned`` for a
    declared key, and the rebuild indexes it from there. The payload catches up
    on the record's own next write."""
    record = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    updated, _ = await drop_price(db, settings, product, fields)
    await record_service.update_record(
        db, updated, record, expected_version=1, data={"title": "One"}, settings=settings
    )
    assert record.data[ORPHANED_KEY] == {"price": "12"}

    restored, _ = await schema_change.apply(
        db, updated, fields_raw=fields, expected_version=2, settings=settings, orphaned="restore"
    )
    assert record_service.read_view(restored, record)["data"]["price"] == "12"
    # Still only under ``_orphaned`` — nothing bulk-rewrote the payload.
    assert record.data == {"title": "One", ORPHANED_KEY: {"price": "12"}}

    from sm_records.index.reindex import reindex_type

    await reindex_type(
        db, restored, resolve_type_id=await type_resolver(db), batch_size=10, field_keys=["price"]
    )
    rows = (
        (await db.execute(select(IndexText).where(IndexText.field_key == "price"))).scalars().all()
    )
    assert [row.value for row in rows] == ["12"]


async def test_the_next_write_after_a_restore_moves_the_value_back_out(
    db, settings, product, fields
):
    record = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    updated, _ = await drop_price(db, settings, product, fields)
    await record_service.update_record(
        db, updated, record, expected_version=1, data={"title": "One"}, settings=settings
    )
    restored, _ = await schema_change.apply(
        db, updated, fields_raw=fields, expected_version=2, settings=settings, orphaned="restore"
    )

    await record_service.update_record(
        db,
        restored,
        record,
        expected_version=2,
        data={"title": "One", "price": "12"},
        settings=settings,
    )
    assert record.data == {"title": "One", "price": "12"}


async def test_discard_removes_the_value_from_every_record(db, settings, product, fields):
    """The one deliberate bulk write of §8 — explicitly asked for, touching
    only the reserved sub-key and the not-yet-migrated copy, and idempotent."""
    migrated = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    stale = await record_service.create_record(
        db, product, data={"title": "Two", "price": "34"}, settings=settings
    )
    updated, _ = await drop_price(db, settings, product, fields)
    await record_service.update_record(
        db, updated, migrated, expected_version=1, data={"title": "One"}, settings=settings
    )

    back, _ = await schema_change.apply(
        db, updated, fields_raw=fields, expected_version=2, settings=settings, orphaned="discard"
    )
    assert migrated.data == {"title": "One"}
    assert stale.data == {"title": "Two"}
    assert record_service.read_view(back, migrated)["data"]["price"] is None


async def test_restoring_a_record_revision_validates_against_the_current_schema(
    db, settings, product
):
    """A revision written under an older schema may simply be unrestorable —
    the correct answer rather than a limitation: storing a payload the current
    schema says cannot exist is the state §8.3 keeps records out of."""
    record = await record_service.create_record(
        db, product, data={"title": "One"}, settings=settings
    )
    created = (await revision_service.list_revisions(db, record))[0]

    required = [
        {"key": "title", "type": "text", "label": "Title"},
        {"key": "price", "type": "text", "label": "Price", "required": True},
    ]
    forced, _ = await schema_change.apply(
        db, product, fields_raw=required, expected_version=1, settings=settings, force=True
    )

    with pytest.raises(ValidationFailed):
        await revision_service.restore(
            db,
            forced,
            record,
            revision_id=created.id,
            expected_version=1,
            settings=settings,
        )


async def test_restoring_a_record_revision_rewrites_the_record_and_logs_the_event(
    db, settings, product
):
    record = await record_service.create_record(
        db, product, data={"title": "One", "price": "12"}, settings=settings
    )
    created = (await revision_service.list_revisions(db, record))[0]
    await record_service.update_record(
        db, product, record, expected_version=1, data={"title": "Two"}, settings=settings
    )

    restored = await revision_service.restore(
        db, product, record, revision_id=created.id, expected_version=2, settings=settings
    )
    assert restored.data["title"] == "One"
    assert restored.version == 3
    assert (await revision_service.list_revisions(db, record))[0].event is RevisionEvent.RESTORE


async def test_restoring_a_revision_of_another_record_is_a_404(db, settings, product):
    mine = await record_service.create_record(db, product, data={"title": "One"}, settings=settings)
    theirs = await record_service.create_record(
        db, product, data={"title": "Two"}, settings=settings
    )
    other = (await revision_service.list_revisions(db, theirs))[0]

    with pytest.raises(NotFound):
        await revision_service.restore(
            db, product, mine, revision_id=other.id, expected_version=1, settings=settings
        )
