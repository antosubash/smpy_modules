"""Record CRUD: validation, the index rows a write leaves behind, concurrency,
and what a delete costs when other records point at the row.

The assertions that matter most are about the index tables and the trash. A
record's payload is history and the index is what queries read (design §8.3),
so "the write succeeded" is not the same claim as "the record is findable" —
each test that writes checks both.
"""

from __future__ import annotations

import pytest
from sm_records.models import (
    IndexText,
    Record,
    RecordRevision,
    RecordStatus,
    RevisionEvent,
)
from sm_records.services import records as service
from sm_records.services import types as type_service
from sm_records.services.errors import (
    Conflict,
    NotFound,
    ValidationFailed,
)
from sm_records.services.revisions import list_revisions
from sm_records.settings import RecordsSettings
from sqlalchemy import select


@pytest.fixture
async def article(db, settings, field_def):
    """A type with an indexed title, a unique sku and a slug source."""
    sku = field_def("sku", "text")
    sku["unique"] = True
    return await type_service.create_type(
        db,
        key="article",
        label="Article",
        fields_raw=[field_def("title", "text"), sku, field_def("body", "longtext", indexed=False)],
        display_field="title",
        slug_field="title",
        settings=settings,
    )


async def text_rows(db, field_key: str, *, include_deleted: bool = False):
    stmt = select(IndexText).where(IndexText.field_key == field_key)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return list((await db.execute(stmt)).scalars().all())


async def test_create_validates_writes_and_indexes(db, settings, article):
    record = await service.create_record(
        db,
        article,
        data={"title": "Hello World", "sku": "A-1", "body": "prose"},
        settings=settings,
        actor="admin",
    )
    assert (record.version, record.schema_version) == (1, article.schema_version)
    assert record.display_title == "Hello World"
    assert record.slug == "hello-world"
    assert record.status is RecordStatus.DRAFT
    assert record.published_at is None
    assert record.created_by == "admin"

    titles = await text_rows(db, "title")
    assert [row.value for row in titles] == ["Hello World"]
    assert titles[0].type_id == article.id
    # `body` is a longtext and cannot be indexed: not queryable, by design §7.2.
    assert await text_rows(db, "body") == []

    history = await list_revisions(db, record)
    assert [r.event for r in history] == [RevisionEvent.CREATE]


async def test_create_refuses_an_invalid_payload(db, settings, article):
    with pytest.raises(ValidationFailed) as excinfo:
        await service.create_record(db, article, data={"title": 1, "nope": "x"}, settings=settings)
    assert any(item["field"] == "nope" for item in excinfo.value.errors)


async def test_create_enforces_the_payload_ceiling(db, article, field_def):
    settings = RecordsSettings(max_payload_bytes=64)
    with pytest.raises(ValidationFailed, match="over the 64-byte limit"):
        await service.create_record(db, article, data={"title": "x" * 200}, settings=settings)


async def test_unique_survives_the_trash_and_frees_on_purge(db, settings, article):
    first = await service.create_record(
        db, article, data={"title": "One", "sku": "A-1"}, settings=settings
    )
    with pytest.raises(Conflict, match="must be unique"):
        await service.create_record(
            db, article, data={"title": "Two", "sku": "A-1"}, settings=settings
        )

    # Design §7.3: index rows survive a soft delete and the trash keeps its
    # claims, so the duplicate is still refused while the original is in it.
    await service.soft_delete_record(db, article, first, settings=settings)
    with pytest.raises(Conflict, match="must be unique"):
        await service.create_record(
            db, article, data={"title": "Two", "sku": "A-1"}, settings=settings
        )

    await service.hard_delete_record(db, article, first)
    second = await service.create_record(
        db, article, data={"title": "Two", "sku": "A-1"}, settings=settings
    )
    assert second.id is not None


async def test_slug_collision_conflicts_including_with_the_trash(db, settings, article):
    first = await service.create_record(db, article, data={"title": "Same"}, settings=settings)
    with pytest.raises(Conflict, match="slug"):
        await service.create_record(db, article, data={"title": "same"}, settings=settings)
    await service.soft_delete_record(db, article, first, settings=settings)
    with pytest.raises(Conflict, match="slug"):
        await service.create_record(db, article, data={"title": "Same"}, settings=settings)


async def test_get_record_is_scoped_to_its_type(db, settings, article, field_def):
    record = await service.create_record(db, article, data={"title": "Hi"}, settings=settings)
    assert (await service.get_record(db, article, record.uuid)).id == record.id

    other = await type_service.create_type(db, key="note", label="Note", settings=settings)
    with pytest.raises(NotFound):
        await service.get_record(db, other, record.uuid)


async def test_update_restamps_the_schema_version_and_rewrites_the_index(db, settings, article):
    record = await service.create_record(db, article, data={"title": "Old"}, settings=settings)
    # The schema moved while this row sat at version 1 — §8.3's lazy payload
    # migration is exactly this: the next write validates against, and stamps,
    # whatever the type says now.
    article.schema_version = 2
    await db.flush()

    updated = await service.update_record(
        db, article, record, expected_version=1, data={"title": "New"}, settings=settings
    )
    assert (updated.version, updated.schema_version) == (2, 2)
    assert updated.display_title == "New"
    assert [row.value for row in await text_rows(db, "title")] == ["New"]
    assert [r.event for r in await list_revisions(db, record)] == [
        RevisionEvent.UPDATE,
        RevisionEvent.CREATE,
    ]


async def test_update_conflicts_on_a_stale_version_and_carries_the_current_row(
    db, settings, article
):
    record = await service.create_record(db, article, data={"title": "One"}, settings=settings)
    await service.update_record(
        db, article, record, expected_version=1, data={"title": "Two"}, settings=settings
    )
    with pytest.raises(Conflict) as excinfo:
        await service.update_record(
            db, article, record, expected_version=1, data={"title": "Three"}, settings=settings
        )
    current = excinfo.value.current
    assert isinstance(current, Record)
    assert (current.version, current.display_title) == (2, "Two")


async def test_published_at_is_set_kept_then_cleared(db, settings, article):
    record = await service.create_record(db, article, data={"title": "A"}, settings=settings)
    assert record.published_at is None

    await service.update_record(
        db,
        article,
        record,
        expected_version=1,
        data={"title": "A"},
        status=RecordStatus.PUBLISHED,
        settings=settings,
    )
    first_published = record.published_at
    assert first_published is not None

    await service.update_record(
        db,
        article,
        record,
        expected_version=2,
        data={"title": "B"},
        status=RecordStatus.PUBLISHED,
        settings=settings,
    )
    assert record.published_at == first_published

    await service.update_record(
        db,
        article,
        record,
        expected_version=3,
        data={"title": "B"},
        status=RecordStatus.DRAFT,
        settings=settings,
    )
    assert record.published_at is None


async def test_list_records_filters_sorts_and_pages(db, settings, article):
    from sm_records.index.query import Filter, FilterOp, Sort

    for title in ("Alpha", "Beta", "Gamma"):
        await service.create_record(db, article, data={"title": title}, settings=settings)

    rows, total, capped, cursor = await service.list_records(
        db, article, settings=settings, sorts=[Sort("title", desc=True)], page=1, page_size=2
    )
    assert (capped, cursor is None) == (False, False)
    assert total == 3
    assert [r.display_title for r in rows] == ["Gamma", "Beta"]

    rows, total, _capped, _cursor = await service.list_records(
        db, article, settings=settings, filters=[Filter("title", FilterOp.EQ, "Beta")]
    )
    assert (total, [r.display_title for r in rows]) == (1, ["Beta"])


async def test_list_records_clamps_the_page_size(db, settings, article):
    small = RecordsSettings(default_page_size=1, max_page_size=2)
    for title in ("A", "B", "C"):
        await service.create_record(db, article, data={"title": title}, settings=small)
    rows, total, _capped, _cursor = await service.list_records(
        db, article, settings=small, page_size=100
    )
    assert (len(rows), total) == (2, 3)


async def test_revisions_are_capped(db, article):
    settings = RecordsSettings(revision_limit=2)
    record = await service.create_record(db, article, data={"title": "v1"}, settings=settings)
    for n, version in ((2, 1), (3, 2), (4, 3)):
        await service.update_record(
            db,
            article,
            record,
            expected_version=version,
            data={"title": f"v{n}"},
            settings=settings,
        )
    kept = (await db.execute(select(RecordRevision))).scalars().all()
    assert len(kept) == 2
    assert [r.version for r in kept] == [3, 4]


async def test_read_view_is_lenient_and_reports_a_stale_schema(db, settings, article):
    record = await service.create_record(db, article, data={"title": "Hi"}, settings=settings)
    view = service.read_view(article, record)
    assert view["data"]["title"] == "Hi"
    assert view["data"]["body"] is None
    assert view["schema_stale"] is False

    article.schema_version = 2
    assert service.read_view(article, record)["schema_stale"] is True
