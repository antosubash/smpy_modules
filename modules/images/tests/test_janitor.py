"""The janitor's purge: trashed rows past the grace period, and their objects.

Keys go before rows, every display generation and rendition an image ever had
is collected (the current ones from the rows, replaced ones from their write-
ahead intents), and a key a surviving row still references is never deleted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing, storage_keys
from sm_images.janitor import purge_expired
from sm_images.models import (
    Collection,
    Image,
    ImportJob,
    ObjectIntent,
    Rendition,
    StepRun,
)
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.storage import ImageStore
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select

from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=8)
GRACE = 7


async def _purge(pipe, **kw):
    async with pipe.db_state.session_factory() as db:
        report = await purge_expired(
            db, pipe.store, now=kw.pop("now", NOW), grace_days=kw.pop("grace", GRACE), **kw
        )
        await db.commit()
    return report


async def _ids(pipe, model, **where) -> list:
    async with pipe.db_state.session_factory() as s:
        stmt = select(model.id).execution_options(include_deleted=True)
        for name, value in where.items():
            stmt = stmt.where(getattr(model, name) == value)
        return list((await s.execute(stmt)).scalars())


async def _intents(pipe) -> list[str]:
    async with pipe.db_state.session_factory() as s:
        return sorted((await s.execute(select(ObjectIntent.key))).scalars())


def _under(pipe, *parts: str) -> list[str]:
    prefix = "/".join(["images", T, *parts])
    stored = pipe.keys()
    return [k for k in stored if k.startswith(prefix)]


async def _blurred_twice(pipe, monkeypatch, coll) -> uuid.UUID:
    """An image with a display copy, renditions, and a *replaced* display
    generation whose after-commit delete failed (only its intent remembers it)."""
    img = await pipe.image(coll)
    await pipe.run(img)
    real = ImageStore.delete_keys

    async def fails(self, keys):
        raise RuntimeError("storage down")

    monkeypatch.setattr(ImageStore, "delete_keys", fails)
    await rerun_image(pipe.runtime, T, img, "force")
    monkeypatch.setattr(ImageStore, "delete_keys", real)
    assert (await pipe.row(img)).display_generation == 2
    return img


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


async def test_purge_removes_storage_and_rows(pipe, blur, monkeypatch):
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img = await _blurred_twice(pipe, monkeypatch, coll)
    keep = await pipe.image(coll)
    prefix = (str(coll.id), str(img))
    replaced = [k for k in _under(pipe, *prefix) if ".1." in k]
    assert replaced and set(replaced) <= set(await _intents(pipe))  # orphaned but known
    await pipe.trash(Image, img, OLD)

    released: list = []

    async def record(db, holds):
        released.extend(holds)

    monkeypatch.setattr(billing, "release_storage", record)
    # A day on: the replaced generations' intents are past ``MIN_INTENT_AGE``.
    report = await _purge(pipe, now=NOW + timedelta(days=1, minutes=1))

    assert report.images == [img] and report.collections == []
    assert _under(pipe, *prefix) == []  # original, both generations, all renditions
    assert _under(pipe, str(coll.id), str(keep))  # the live neighbour is untouched
    assert await _ids(pipe, Image) == [keep]
    assert await _ids(pipe, StepRun, image_id=img) == []
    assert await _ids(pipe, Rendition, image_id=img) == []
    assert not [k for k in await _intents(pipe) if k.startswith("/".join(["images", T, *prefix]))]
    assert [h[0] for h in released] == [img]


async def test_purge_of_a_collection_takes_its_map_and_import_staging(pipe, blur):
    coll = await pipe.collection({"acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    job_id = uuid.uuid4()
    staged = storage_keys.import_key(T, str(job_id), "feed.geojson")
    map_key = storage_keys.map_key(T, str(coll.id))
    for key in (staged, map_key):
        await pipe.store.put(key, b"x", content_type="application/octet-stream", size=1)
    async with pipe.db_state.session_factory() as s:
        s.add(ImportJob(id=job_id, collection_id=coll.id, source_key=staged, staged_keys=[staged]))
        await s.commit()
    await pipe.trash(Collection, coll.id, OLD)  # its image itself is not trashed

    report = await _purge(pipe)
    assert report.collections == [coll.id] and report.images == [img]
    assert pipe.keys() == []
    assert await _ids(pipe, Collection) == [] and await _ids(pipe, Image) == []
    assert await _ids(pipe, ImportJob) == []


async def test_purge_dry_run(pipe, blur):
    coll = await pipe.collection({"acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    await pipe.trash(Image, img, OLD)
    before = pipe.keys()

    report = await _purge(pipe, dry_run=True)
    assert report.dry_run and report.images == [img]
    assert sorted(report.keys) == before
    assert pipe.keys() == before
    assert await _ids(pipe, Image) == [img]


async def test_purge_respects_grace(pipe, blur):
    coll = await pipe.collection({"acme.blur": {}})
    recent, live = await pipe.image(coll), await pipe.image(coll)
    await pipe.trash(Image, recent, NOW - timedelta(days=GRACE - 1))
    before = pipe.keys()

    report = await _purge(pipe)
    assert (report.images, report.collections, report.keys) == ([], [], [])
    assert pipe.keys() == before
    assert sorted(await _ids(pipe, Image)) == sorted([recent, live])
    # Once its grace has run out it goes; the live one never does.
    assert (await _purge(pipe, now=NOW + timedelta(days=2))).images == [recent]
    assert await _ids(pipe, Image) == [live]


async def test_purge_never_deletes_a_key_a_live_row_references(pipe, blur):
    coll = await pipe.collection({})
    gone, live = await pipe.image(coll), await pipe.image(coll)
    shared = (await pipe.row(gone)).storage_key
    async with pipe.db_state.session_factory() as s:
        row = await s.get(Image, live)
        row.display_key = shared
        await s.commit()
    await pipe.trash(Image, gone, OLD)

    report = await _purge(pipe)
    assert report.images == [gone] and report.kept == [shared]
    assert await pipe.store.exists(shared)


async def test_purge_cap_bounds_one_pass(pipe, blur):
    coll = await pipe.collection({})
    imgs = [await pipe.image(coll) for _ in range(3)]
    for img in imgs:
        await pipe.trash(Image, img, OLD)
    assert len((await _purge(pipe, cap=2)).images) == 2
    assert len((await _purge(pipe, cap=2)).images) == 1
    assert await _ids(pipe, Image) == []
