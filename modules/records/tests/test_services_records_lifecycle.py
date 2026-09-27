"""The delete lifecycle: relations on write, ``on_delete`` on trash, and purge.

Split from ``test_services_records`` for the 300-line cap, and it is where the
cap falls naturally: everything here is about a record's existence and what
other records' references to it cost (design §9), rather than about its
content.

The type keys differ from the sibling file's on purpose. ``schema.compile``'s
model cache is process-global and keyed on ``(type key, schema_version)``, so
two differently-shaped types sharing a key inside one test session would share
a validator.
"""

from __future__ import annotations

import pytest
from sm_records.models import IndexRef, IndexText, Record, RevisionEvent
from sm_records.services import records as service
from sm_records.services import types as type_service
from sm_records.services.errors import Conflict, ReferencedByOthers, ValidationFailed
from sm_records.services.revisions import list_revisions
from sqlalchemy import select


@pytest.fixture
async def story(db, settings, field_def):
    return await type_service.create_type(
        db,
        key="story",
        label="Story",
        fields_raw=[field_def("title", "text")],
        display_field="title",
        slug_field="title",
        settings=settings,
    )


async def text_rows(db, field_key: str, *, include_deleted: bool = False):
    stmt = select(IndexText).where(IndexText.field_key == field_key)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return list((await db.execute(stmt)).scalars().all())


async def relation_setup(db, settings, field_def, on_delete: str):
    """A ``brand`` and a ``product`` whose relation carries ``on_delete``."""
    brand = await type_service.create_type(
        db, key="brand", label="Brand", fields_raw=[field_def("name", "text")], settings=settings
    )
    product = await type_service.create_type(
        db,
        key="product",
        label="Product",
        fields_raw=[
            field_def("name", "text"),
            field_def("maker", "relation", target_type="brand", on_delete=on_delete),
        ],
        settings=settings,
    )
    target = await service.create_record(db, brand, data={"name": "Acme"}, settings=settings)
    referrer = await service.create_record(
        db,
        product,
        data={"name": "Anvil", "maker": {"type": "brand", "uuid": target.uuid}},
        settings=settings,
    )
    return brand, product, target, referrer


async def test_relation_target_must_exist_and_match_its_type(db, settings, field_def):
    _, product, target, _ = await relation_setup(db, settings, field_def, "restrict")
    refs = (await db.execute(select(IndexRef))).scalars().all()
    assert [(r.field_key, r.target_uuid) for r in refs] == [("maker", target.uuid)]

    with pytest.raises(ValidationFailed, match="no record with uuid"):
        await service.create_record(
            db,
            product,
            data={"name": "X", "maker": {"type": "brand", "uuid": "0" * 32}},
            settings=settings,
        )


async def test_restrict_refuses_a_delete_that_is_referenced(db, settings, field_def):
    brand, _, target, referrer = await relation_setup(db, settings, field_def, "restrict")
    with pytest.raises(ReferencedByOthers) as excinfo:
        await service.soft_delete_record(db, brand, target, settings=settings)
    assert excinfo.value.referrers == [referrer.uuid]
    assert target.is_deleted is False


async def test_set_null_clears_the_reference_and_its_index_row(db, settings, field_def):
    brand, _, target, referrer = await relation_setup(db, settings, field_def, "set_null")
    await service.soft_delete_record(db, brand, target, settings=settings)

    assert target.is_deleted is True
    assert referrer.is_deleted is False
    assert referrer.data["maker"] is None
    assert (await db.execute(select(IndexRef))).scalars().first() is None


async def test_set_null_bumps_the_referrer_and_writes_it_a_revision(db, settings, field_def):
    """Nulling somebody else's reference is an edit of their record, so it
    goes through the same bump-and-revise path a PUT does — or a client
    holding the pre-delete version overwrites it under optimistic concurrency
    that reports no conflict, and the history panel never mentions it."""
    brand, _, target, referrer = await relation_setup(db, settings, field_def, "set_null")
    assert referrer.version == 1
    before = len(await list_revisions(db, referrer))

    await service.soft_delete_record(db, brand, target, settings=settings, actor="admin")

    # ``updated_by`` is the framework listener's to stamp, from the request's
    # user context — the actor is asserted on the revision, which this module
    # writes itself.
    assert referrer.version == 2
    revisions = await list_revisions(db, referrer)
    assert len(revisions) == before + 1
    latest = revisions[0]
    assert (latest.event, latest.version, latest.created_by) == (RevisionEvent.UPDATE, 2, "admin")
    assert latest.data["maker"] is None


async def test_cascade_trashes_the_referrer(db, settings, field_def):
    brand, _, target, referrer = await relation_setup(db, settings, field_def, "cascade")
    await service.soft_delete_record(db, brand, target, settings=settings, actor="admin")

    assert (target.is_deleted, referrer.is_deleted) == (True, True)
    assert referrer.deleted_by == "admin"
    latest = (await list_revisions(db, referrer))[0]
    assert latest.event is RevisionEvent.DELETE


async def test_soft_delete_keeps_index_rows_and_restore_rebuilds_them(db, settings, story):
    record = await service.create_record(db, story, data={"title": "Kept"}, settings=settings)
    await service.soft_delete_record(db, story, record, settings=settings, actor="admin")

    assert record.deleted_at is not None
    # §7.3: the rows stay; the join to records_record is what hides the row.
    assert [row.value for row in await text_rows(db, "title", include_deleted=True)] == ["Kept"]

    trashed = await service.get_deleted_record(db, story, record.uuid)
    restored = await service.restore_record(db, story, trashed, settings=settings)
    assert (restored.is_deleted, restored.deleted_at, restored.deleted_by) == (False, None, None)
    assert [row.value for row in await text_rows(db, "title")] == ["Kept"]
    assert (await list_revisions(db, record))[0].event is RevisionEvent.RESTORE


async def test_hard_delete_needs_the_trash_first_and_drops_the_index(db, settings, story):
    record = await service.create_record(db, story, data={"title": "Bye"}, settings=settings)
    with pytest.raises(Conflict, match="trash"):
        await service.hard_delete_record(db, story, record)

    await service.soft_delete_record(db, story, record, settings=settings)
    await service.hard_delete_record(db, story, record)
    assert await text_rows(db, "title", include_deleted=True) == []
    stmt = select(Record).execution_options(include_deleted=True)
    assert (await db.execute(stmt)).scalars().first() is None


async def test_a_purge_marks_the_session_as_having_written(db, settings, story):
    """A purge is core ``DELETE`` only, and the framework decides whether to
    commit the request from an ``after_flush`` listener that core DML never
    fires. Without the explicit flag the rows would quietly come back."""
    from simple_module_db.listeners import SESSION_HAS_WRITES_KEY

    record = await service.create_record(db, story, data={"title": "Bye"}, settings=settings)
    await service.soft_delete_record(db, story, record, settings=settings)
    db.info.pop(SESSION_HAS_WRITES_KEY, None)

    await service.hard_delete_record(db, story, record)
    assert db.info.get(SESSION_HAS_WRITES_KEY) is True
