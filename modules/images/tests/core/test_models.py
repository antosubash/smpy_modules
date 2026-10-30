"""Constraints the data model enforces itself, on SQLite and (opt-in) Postgres."""

from __future__ import annotations

import uuid

import pytest
from sm_images.models import (
    Collection,
    Image,
    ImportItem,
    ImportJob,
    ImportKind,
    LocationSource,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def _collection(db, slug="c") -> Collection:
    coll = Collection(slug=slug, name=slug, owner_id="u1")
    db.add(coll)
    await db.flush()
    return coll


def _image(coll: Collection, **kw) -> Image:
    kw.setdefault("storage_key", f"images/t/c/{uuid.uuid4()}/original.jpg")
    return Image(
        collection_id=coll.id, filename="a.jpg", content_type="image/jpeg", size_bytes=1, **kw
    )


async def test_external_id_dedupe_index(db):
    coll = await _collection(db)
    db.add(_image(coll, external_source="s", external_id="e1"))
    await db.flush()
    # No external id: any number of rows.
    db.add(_image(coll))
    db.add(_image(coll))
    # Same id under another source, or in another collection: fine.
    other = await _collection(db, "d")
    db.add(_image(coll, external_source="t", external_id="e1"))
    db.add(_image(other, external_source="s", external_id="e1"))
    await db.flush()
    db.add(_image(coll, external_source="s", external_id="e1"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_paired_coordinates_check(db):
    coll = await _collection(db)
    db.add(_image(coll, lat=1.0))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_location_source_is_comparable_in_sql(db):
    coll = await _collection(db)
    db.add(_image(coll, lat=0.0, lng=0.0, location_source=LocationSource.IMPORT_))
    await db.flush()
    rows = (
        (await db.execute(select(Image).where(Image.location_source < LocationSource.MANUAL)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_import_item_unique_per_feature(db):
    coll = await _collection(db)
    job = ImportJob(collection_id=coll.id, kind=ImportKind.GEOJSON_URL)
    db.add(job)
    await db.flush()
    db.add(ImportItem(job_id=job.id, feature_index=0))
    db.add(ImportItem(job_id=job.id, feature_index=1))
    await db.flush()
    db.add(ImportItem(job_id=job.id, feature_index=1))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_soft_delete_hides_collection(db):
    coll = await _collection(db)
    coll.is_deleted = True
    await db.flush()
    assert (await db.execute(select(Collection))).scalars().all() == []
    gone = await db.execute(select(Collection).execution_options(include_deleted=True))
    assert len(gone.scalars().all()) == 1
