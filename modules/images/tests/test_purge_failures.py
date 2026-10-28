"""Phase 3 fixes 2, 3, 7 and 8: a purge pass that cannot finish everything.

* A row ``SKIP LOCKED`` passed over is still there: its collection - and the
  collection's own objects (the map) - stay for the next pass (2).
* An upload session's multipart upload is aborted *before* its row goes; a
  failed abort keeps the session and its collection (3).
* An intent younger than ``MIN_INTENT_AGE`` may be an in-flight ``stage()``:
  its object and intent are left alone (7).
* One key that will not delete excludes only its own image, which is
  recorded and tried last from then on (8).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sm_images import purge, purge_select, storage_keys
from sm_images.models import Collection, Image, ObjectIntent, UploadSession, UploadStatus
from sm_images.storage import ImageStore
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.pipeline_support import use_steps
from tests.test_janitor import NOW, OLD, _ids, _intents, _purge

T = DEFAULT_TENANT


@pytest.fixture(autouse=True)
def _steps():
    use_steps()


def _skip_locked(monkeypatch, *ids: uuid.UUID) -> set[uuid.UUID]:
    """SQLite has no row locks: ``SKIP LOCKED`` passes over the returned set's
    ids (clear it to release them)."""
    locked = set(ids)
    real = purge_select._locked

    def fake(stmt):
        desc = stmt.column_descriptions
        if locked and desc and desc[0].get("entity") is Image:
            stmt = stmt.where(Image.id.not_in(sorted(locked)))
        return real(stmt)

    monkeypatch.setattr(purge_select, "_locked", fake)
    return locked


async def _with_map(pipe, coll) -> str:
    key = storage_keys.map_key(T, str(coll.id))
    await pipe.store.put(key, b"m", content_type="application/octet-stream", size=1)
    return key


def _failing_deletes(monkeypatch, bad) -> list:
    """``ImageStore.delete_keys`` fails for any batch holding a key ``bad``
    matches; the returned list holds that predicate (clear it to heal)."""
    real = ImageStore.delete_keys
    rule = [bad]

    async def delete_keys(self, keys):
        keys = list(keys)
        if rule and any(rule[0](k) for k in keys):
            raise RuntimeError("storage refused")
        return await real(self, keys)

    monkeypatch.setattr(ImageStore, "delete_keys", delete_keys)
    return rule


async def test_a_skipped_locked_image_keeps_its_collection(pipe, monkeypatch):
    coll = await pipe.collection({})
    free, held = await pipe.image(coll), await pipe.image(coll)
    map_key = await _with_map(pipe, coll)
    await pipe.trash(Collection, coll.id, OLD)
    locked = _skip_locked(monkeypatch, held)

    report = await _purge(pipe)
    assert report.images == [free] and report.collections == []
    assert await _ids(pipe, Collection) == [coll.id]
    assert await pipe.store.exists(map_key)  # collection-level: only with its row
    assert await _ids(pipe, Image) == [held]

    locked.clear()
    report = await _purge(pipe)
    assert report.images == [held] and report.collections == [coll.id]
    assert pipe.keys() == []


async def test_an_upload_session_is_aborted_before_its_row_goes(pipe, monkeypatch):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    staged = storage_keys.original_key(T, str(coll.id), str(uuid.uuid4()), "jpg")
    await pipe.store.put(staged, b"part", content_type="image/jpeg", size=4)
    async with pipe.db_state.session_factory() as s:
        s.add(
            UploadSession(
                collection_id=coll.id,
                image_id=uuid.uuid4(),
                storage_key=staged,
                backend_upload_id="mp-1",
                size=4,
                content_type="image/jpeg",
                status=UploadStatus.OPEN,
                expires_at=OLD,
            )
        )
        await s.commit()
    await pipe.trash(Collection, coll.id, OLD)

    async def refuses(key, upload):
        raise RuntimeError("abort failed")

    monkeypatch.setattr(pipe.backend, "abort_multipart", refuses, raising=False)
    report = await _purge(pipe)
    assert report.images == [img] and report.collections == []
    assert await _ids(pipe, UploadSession) and await _ids(pipe, Collection) == [coll.id]
    assert await pipe.store.exists(staged)

    aborted: list = []

    async def aborts(key, upload):
        aborted.append((key, upload, bool(await _ids(pipe, UploadSession))))

    monkeypatch.setattr(pipe.backend, "abort_multipart", aborts, raising=False)
    report = await _purge(pipe)
    assert report.collections == [coll.id]
    assert aborted == [(staged, "mp-1", True)]  # the row still existed when it ran
    assert await _ids(pipe, UploadSession) == [] and await _ids(pipe, Collection) == []
    assert pipe.keys() == []


async def test_a_young_intent_under_a_purged_image_is_left_alone(pipe):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    prefix = storage_keys.image_prefix(T, str(coll.id), str(img))
    old, young = f"{prefix}display.1.old.jpg", f"{prefix}display.2.young.jpg"
    for key, at in ((old, OLD), (young, NOW - timedelta(hours=1))):
        await pipe.store.put(key, b"x", content_type="image/jpeg", size=1)
        async with pipe.db_state.session_factory() as s:
            s.add(ObjectIntent(key=key, created_at=at))
            await s.commit()
    await pipe.trash(Image, img, OLD)

    report = await _purge(pipe)
    assert report.images == [img] and young not in report.keys and old in report.keys
    assert await pipe.store.exists(young) and not await pipe.store.exists(old)
    assert await _intents(pipe) == [young]  # the intent reaper's, once it is old


async def test_one_undeletable_key_excludes_only_its_image(pipe, monkeypatch):
    coll = await pipe.collection({})
    stuck, ok = await pipe.image(coll), await pipe.image(coll)
    await pipe.trash(Image, stuck, OLD - timedelta(days=1))  # oldest: first in line
    await pipe.trash(Image, ok, OLD)
    _failing_deletes(monkeypatch, lambda k: str(stuck) in k)

    report = await _purge(pipe)
    assert report.images == [ok] and report.failed == [stuck]
    assert await _ids(pipe, Image) == [stuck]
    async with pipe.db_state.session_factory() as s:
        stmt = select(Image.purge_failed_at).execution_options(include_deleted=True)
        assert (await s.execute(stmt)).scalar_one() is not None


async def test_a_recorded_failure_goes_to_the_back_of_the_line(pipe, monkeypatch):
    coll = await pipe.collection({})
    stuck = await pipe.image(coll)
    others = [await pipe.image(coll) for _ in range(2)]
    await pipe.trash(Image, stuck, OLD - timedelta(days=1))
    for img in others:
        await pipe.trash(Image, img, OLD)
    _failing_deletes(monkeypatch, lambda k: str(stuck) in k)

    assert (await _purge(pipe, cap=1)).failed == [stuck]
    # The stuck image no longer takes the whole budget of every pass.
    assert len((await _purge(pipe, cap=1)).images) == 1
    assert len((await _purge(pipe, cap=1)).images) == 1
    assert await _ids(pipe, Image) == [stuck]


async def test_an_undeletable_map_keeps_the_collection(pipe, monkeypatch):
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    map_key = await _with_map(pipe, coll)
    await pipe.trash(Collection, coll.id, OLD)
    rule = _failing_deletes(monkeypatch, lambda k: k == map_key)

    report = await _purge(pipe)
    assert report.images == [img] and report.collections == []
    assert await _ids(pipe, Collection) == [coll.id] and await _ids(pipe, Image) == []
    rule.clear()
    assert (await _purge(pipe)).collections == [coll.id]
    assert pipe.keys() == []


@pytest.mark.skipif(not USING_POSTGRES, reason="a real row lock needs Postgres")
async def test_a_row_locked_on_postgres_keeps_its_collection(pipe):
    coll = await pipe.collection({})
    free, held = await pipe.image(coll), await pipe.image(coll)
    map_key = await _with_map(pipe, coll)
    await pipe.trash(Collection, coll.id, OLD)
    async with pipe.db_state.session_factory() as holder:  # a step completing on it
        lock = select(Image.id).where(Image.id == held).with_for_update()
        await holder.execute(lock.execution_options(include_deleted=True))
        report = await _purge(pipe)
        await holder.rollback()
    assert report.images == [free] and report.collections == []
    assert await pipe.store.exists(map_key) and await _ids(pipe, Collection) == [coll.id]
    report = await _purge(pipe)
    assert report.images == [held] and report.collections == [coll.id]


def test_the_min_intent_age_is_one_constant():
    from sm_images import janitor

    assert janitor.MIN_INTENT_AGE is purge.MIN_INTENT_AGE
