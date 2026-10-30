"""Phase 3 round 2: purge failures that must not hurt a neighbour.

* A key two selected images share is deleted only once *both* are cleared:
  if one of them fails and is kept, its bytes must still be there.
* A collection whose purge failed goes to the back of later passes, so with
  a tight budget it cannot take every pass from the others.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_images.models import Collection, Image
from sqlalchemy import select, update

from tests.jobs.test_janitor import OLD, _ids, _purge
from tests.jobs.test_purge_failures import _failing_deletes
from tests.support.pipeline import use_steps


@pytest.fixture(autouse=True)
def _steps():
    use_steps()


async def test_a_shared_key_survives_while_one_owner_is_kept(pipe, monkeypatch):
    coll = await pipe.collection({})
    gone, kept = await pipe.image(coll), await pipe.image(coll)
    shared = (await pipe.row(gone)).storage_key
    own = (await pipe.row(kept)).storage_key
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Image).where(Image.id == kept).values(display_key=shared))
        await s.commit()
    for img in (gone, kept):
        await pipe.trash(Image, img, OLD)
    _failing_deletes(monkeypatch, lambda k: k == own)

    report = await _purge(pipe)
    assert report.images == [gone] and report.failed == [kept]
    assert shared not in report.keys
    assert await pipe.store.exists(shared)  # the kept image still shows it
    assert await pipe.store.exists(own)
    assert await _ids(pipe, Image) == [kept]


async def test_a_shared_key_goes_once_every_owner_is_cleared(pipe):
    coll = await pipe.collection({})
    a, b = await pipe.image(coll), await pipe.image(coll)
    shared = (await pipe.row(a)).storage_key
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Image).where(Image.id == b).values(display_key=shared))
        await s.commit()
    for img in (a, b):
        await pipe.trash(Image, img, OLD)

    report = await _purge(pipe)
    assert sorted(report.images) == sorted([a, b]) and shared in report.keys
    assert pipe.keys() == []


async def test_a_failing_collection_does_not_take_every_pass(pipe, monkeypatch):
    stuck_coll, ok_coll = await pipe.collection({}), await pipe.collection({})
    stuck, ok = await pipe.image(stuck_coll), await pipe.image(ok_coll)
    await pipe.trash(Collection, stuck_coll.id, OLD - timedelta(days=1))  # first in line
    await pipe.trash(Collection, ok_coll.id, OLD)
    _failing_deletes(monkeypatch, lambda k: str(stuck) in k)

    assert (await _purge(pipe, cap=1)).failed == [stuck]
    assert (await _purge(pipe, cap=1)).images == [ok]  # not the stuck one again
    assert (await _purge(pipe, cap=1)).collections == [ok_coll.id]
    assert await _ids(pipe, Collection) == [stuck_coll.id]
    async with pipe.db_state.session_factory() as s:
        stmt = select(Collection.purge_failed_at).execution_options(include_deleted=True)
        assert (await s.execute(stmt)).scalar_one() is not None
