"""The storage gauge on direct-upload ``complete``: a replay is answered before
the capacity check, a refused hold keeps the upload for a retry, and a losing
concurrent complete releases only the hold it reserved itself."""

from __future__ import annotations

import uuid

from simple_module_db import finalize_session
from sm_images.core import constants
from sm_images.ingest import Duplicate, IngestMeta, IngestService
from sm_images.models import Collection, Image
from sm_images.storage import store_for
from sqlalchemy import select

from tests.support.direct import complete, send_parts, start
from tests.support.upload import all_rows, jpeg, make_collection, stored

QUOTA = constants.CODE_QUOTA_EXCEEDED


async def _uploaded(client, data: bytes) -> tuple[str, dict, list]:
    cid = await make_collection(client)
    created = (await start(client, cid, data)).json()
    return cid, created, await send_parts(client, created, data)


async def test_a_replayed_complete_at_quota_answers_the_image(uploads, gauge, small_parts):
    data = jpeg(size=(64, 48))
    _, created, parts = await _uploaded(uploads, data)
    first = await complete(uploads, created["upload_id"], parts)
    assert first.status_code == 200, first.text
    uploads.app.state.billing_usage = gauge
    gauge.limit = 0  # full now: a replay must still answer the stored image
    again = await complete(uploads, created["upload_id"], parts)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]


async def test_a_refused_hold_keeps_the_upload_for_a_retry(uploads, gauge, small_parts):
    data = jpeg(size=(64, 48))
    _, created, parts = await _uploaded(uploads, data)
    gauge.limit = len(data) - 1  # no pre-flight (billing not running here): the hold refuses
    refused = await complete(uploads, created["upload_id"], parts)
    assert refused.status_code == 402, refused.text
    assert refused.json()["code"] == QUOTA
    assert await all_rows(uploads) == []
    assert len(stored(uploads.storage)) == 1  # the assembled upload is kept
    gauge.limit = None
    retried = await complete(uploads, created["upload_id"], parts)
    assert retried.status_code == 200, retried.text
    (row,) = await all_rows(uploads)
    assert gauge.holds[row.storage_hold_id].status == "committed"


async def test_a_losing_complete_releases_only_its_own_hold(uploads, gauge, small_parts):
    """Two completes of one upload: the loser reaches ``add_image`` after the
    winner's row committed, and must not release the winner's hold."""
    uploads.app.state.sm_images.settings.dedupe_by_hash = False
    data = jpeg(size=(64, 48))
    cid, created, parts = await _uploaded(uploads, data)
    won = await complete(uploads, created["upload_id"], parts)
    assert won.status_code == 200, won.text
    image_id = uuid.UUID(won.json()["id"])
    async with uploads.db_state.session_factory() as db:
        row = (await db.execute(select(Image).where(Image.id == image_id))).scalar_one()
        coll = (
            await db.execute(select(Collection).where(Collection.id == uuid.UUID(cid)))
        ).scalar_one()
        winner = row.storage_hold_id
        ingest = IngestService(db, store_for(uploads.app), uploads.app.state.sm_images.settings)
        lost = await ingest.add_image(
            coll,
            staged_key=row.storage_key,
            image_id=image_id,
            filename="big.jpg",
            meta=IngestMeta(),
            source=constants.SOURCE_UPLOAD,
        )
        await finalize_session(db)
    assert lost == Duplicate(image_id)
    assert gauge.holds[winner].status == "committed"
    losers = [h for h in gauge.holds.values() if h.id != winner]
    assert [h.status for h in losers] == ["released"]
