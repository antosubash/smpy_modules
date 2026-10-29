"""A storage hold must not outlive the request that took it.

Ingest finishes its op in the insert's savepoint, so a failure anywhere later
in the request - ``queue_auto_run``, the route, the commit - rolls the finish
back with the row, and the op stays claimed for ``INGEST_CLAIM``: a retry
under a quota that fits one image is refused (402) for half an hour. Every op
the request acquired is handed back in its own transaction after the
rollback, so the retry is admitted and exactly one hold stays committed.
"""

from __future__ import annotations

import pytest
from sm_images import pipeline
from sm_images.imports import jobs
from sm_images.models import ItemStatus

from tests.direct_support import complete, send_parts, start
from tests.import_support import b64 as feature_b64
from tests.import_support import feature
from tests.test_upload_base64 import b64, post
from tests.upload_support import all_rows, jpeg, make_collection


def _auto_run_fails_once(monkeypatch) -> None:
    real = pipeline.queue_auto_run
    armed = {"on": True}

    async def queue(*args, **kwargs):
        if armed.pop("on", False):
            raise RuntimeError("queue blip")
        return await real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "queue_auto_run", queue)


async def _one_committed_hold(client, gauge) -> None:
    (row,) = await all_rows(client)
    live = {h.id: h.status for h in gauge.holds.values() if h.status != "released"}
    assert live == {row.storage_hold_id: "committed"}


async def test_direct_complete_releases_the_hold_when_auto_run_fails(
    uploads, gauge, small_parts, monkeypatch
):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    created = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, created, data)
    gauge.limit = len(data)  # room for exactly one image
    _auto_run_fails_once(monkeypatch)
    with pytest.raises(Exception):  # noqa: B017 - an unhandled 500, raised through the transport
        await complete(uploads, created["upload_id"], parts)
    assert await all_rows(uploads) == []

    retried = await complete(uploads, created["upload_id"], parts)
    assert retried.status_code == 200, retried.text
    await _one_committed_hold(uploads, gauge)


async def test_base64_upload_releases_the_hold_when_auto_run_fails(uploads, gauge, monkeypatch):
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    gauge.limit = len(data)
    _auto_run_fails_once(monkeypatch)
    with pytest.raises(Exception):  # noqa: B017 - an unhandled 500, raised through the transport
        await post(uploads, cid, filename="a.jpg", data=b64(data))
    assert await all_rows(uploads) == []

    retried = await post(uploads, cid, filename="a.jpg", data=b64(data))
    assert retried.status_code == 200, retried.text
    await _one_committed_hold(uploads, gauge)


async def test_an_import_settlement_that_loses_releases_its_hold(imp, gauge, monkeypatch):
    """``settle_bytes`` rolls back when the item's counter bump loses: the
    image row goes, and so must the hold it took (now, not after the claim)."""
    real = jobs.bump
    armed = {"on": True}

    async def bump(db, tenant, job_id, counts, generation):
        if ItemStatus.DONE in counts and armed.pop("on", False):
            return False
        return await real(db, tenant, job_id, counts, generation)

    monkeypatch.setattr(jobs, "bump", bump)
    job = await imp.job([feature({"img": feature_b64("red")})])
    await imp.run(job)
    assert not armed, "the bump was never lost"
    images = await imp.images()
    held = {h.id: h.status for h in gauge.holds.values() if h.status != "released"}
    assert held == {i.storage_hold_id: "committed" for i in images}
