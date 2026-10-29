"""The ``images.storage_bytes`` gauge at ingest: the 402 pre-flight on upload,
direct-upload complete and import start, one committed hold per image, the
import item that does not fit, the no-billing no-op and the fail-closed seam."""

from __future__ import annotations

import sys
import types

import pytest
from sm_images import billing, constants
from sm_images.models import Image
from sqlalchemy import select

from tests.import_support import b64, feature
from tests.test_direct_upload import complete, send_parts, small_parts, start  # noqa: F401
from tests.upload_support import BASE, OLGA, all_rows, jpeg, make_collection, post_files, stored

QUOTA = constants.CODE_QUOTA_EXCEEDED


async def _rows(client) -> list[Image]:
    async with client.db_state.session_factory() as s:
        return list((await s.execute(select(Image))).scalars())


def test_the_meter_is_a_gauge_in_bytes():
    from sm_billing.contracts.metering import MeterKind
    from sm_billing.metering.registry import MeterRegistry

    app = types.SimpleNamespace(state=types.SimpleNamespace(billing_meters=MeterRegistry()))
    assert billing.register_meter(app) is True
    meter = app.state.billing_meters.get("images.storage_bytes")
    assert (meter.kind, meter.unit, meter.label_key) == (
        MeterKind.GAUGE,
        "bytes",
        "images.meters.storage_bytes",
    )
    assert billing.register_meter(types.SimpleNamespace(state=types.SimpleNamespace())) is False


async def test_no_billing_is_a_no_op_and_storage_bytes_is_kept(uploads):
    data = jpeg()
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("a.jpg", data, "image/jpeg")])
    assert got.status_code == 200, got.text
    (row,) = await _rows(uploads)
    assert (row.storage_bytes, row.storage_hold_id) == (len(data), None)


async def test_upload_takes_one_committed_hold_for_the_original(uploads, gauge):
    uploads.app.state.billing_usage = gauge
    data = jpeg()
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("a.jpg", data, "image/jpeg")])
    assert got.status_code == 200, got.text
    (row,) = await _rows(uploads)
    (hold,) = gauge.live()
    assert (hold.id, hold.status, hold.quantity) == (row.storage_hold_id, "committed", len(data))
    assert gauge.keys == {billing.hold_key(row.id, 0): hold.id}


async def test_upload_over_quota_is_402_and_stores_nothing(uploads, gauge):
    uploads.app.state.billing_usage = gauge
    gauge.limit = 10
    cid = await make_collection(uploads)
    one = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")])
    assert one.status_code == 402, one.text
    assert one.json()["code"] == QUOTA
    files = [("a.jpg", jpeg(), "image/jpeg"), ("b.jpg", jpeg(color="blue"), "image/jpeg")]
    two = await post_files(uploads, cid, files)  # the batch's total is checked
    assert two.status_code == 402, two.text
    b64_body = {"data": b64(), "filename": "c.jpg"}
    three = await uploads.post(f"{BASE}/{cid}/images/base64", json=b64_body, headers=OLGA)
    assert three.status_code == 402, three.text
    assert await all_rows(uploads) == [] and stored(uploads.storage) == []
    assert gauge.live() == []


async def test_a_hold_refused_after_the_check_fails_that_file_only(uploads, gauge):
    """No pre-flight (billing not running in the web process): the hold is
    still the enforcement, per file."""
    first, second = jpeg(), jpeg(color="blue")
    gauge.limit = len(first)
    cid = await make_collection(uploads)
    files = [("a.jpg", first, "image/jpeg"), ("b.jpg", second, "image/jpeg")]
    got = await post_files(uploads, cid, files)
    assert got.status_code == 200, got.text
    a, b = got.json()["results"]
    assert a["status"] == "created" and (b["status"], b["code"]) == ("error", QUOTA)
    (row,) = await _rows(uploads)
    assert [h.id for h in gauge.live("committed")] == [row.storage_hold_id]
    assert len(stored(uploads.storage)) == 1


async def test_direct_complete_checks_first(uploads, gauge, small_parts):  # noqa: F811
    uploads.app.state.billing_usage = gauge
    data = jpeg(size=(64, 48))
    cid = await make_collection(uploads)
    created = (await start(uploads, cid, data)).json()
    parts = await send_parts(uploads, created, data)
    gauge.limit = len(data) - 1
    got = await complete(uploads, created["upload_id"], parts)
    assert got.status_code == 402, got.text
    assert got.json()["code"] == QUOTA
    assert await all_rows(uploads) == []
    gauge.limit = None
    again = await complete(uploads, created["upload_id"], parts)
    assert again.status_code == 200, again.text
    (row,) = await _rows(uploads)
    assert (row.storage_bytes, gauge.live()[0].quantity) == (len(data), len(data))


async def test_import_start_is_402_when_the_gauge_is_full(uploads, gauge):
    uploads.app.state.billing_usage = gauge
    gauge.limit = 0
    cid = await make_collection(uploads)
    got = await uploads.post(
        f"{BASE}/{cid}/imports",
        data={"kind": "geojson_base64", "mapping": '{"image_prop": "img"}'},
        files={"file": ("f.geojson", b'{"type":"FeatureCollection","features":[]}')},
        headers=OLGA,
    )
    assert got.status_code == 402, got.text
    assert got.json()["code"] == QUOTA
    zipped = await uploads.post(
        f"{BASE}/{cid}/imports/zip", json={"filename": "a.zip", "size": 10}, headers=OLGA
    )
    assert zipped.status_code == 402, zipped.text


async def test_an_import_item_that_does_not_fit_fails_quota_exceeded(imp, gauge):
    small = b64("red")
    gauge.limit = len(__import__("base64").b64decode(small))
    job = await imp.job([feature({"img": small}), feature({"img": b64("blue", (16, 12))})])
    assert await imp.run(job) == "completed"
    items = await imp.items(job)
    assert [i.last_error for i in items] == [None, QUOTA]
    (image,) = await imp.images()
    assert [h.id for h in gauge.live("committed")] == [image.storage_hold_id]
    assert len(imp.stored()) == 2  # the one original, plus the job's staged source


def test_an_installed_billing_that_cannot_meter_fails_closed(monkeypatch):
    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    monkeypatch.setitem(sys.modules, constants.BILLING_USAGE_MODULE, types.ModuleType("old"))
    with pytest.raises(RuntimeError, match="usage_meter"):
        billing.storage_meter(object())


async def test_the_seam_holds_against_real_billing(tmp_path, monkeypatch):
    """``usage_meter`` (a worker's view: no registry) reserves, commits and
    releases a hold on ``images.storage_bytes`` in billing's own tables."""
    from simple_module_db import init_db
    from sm_billing.models import Base, UsageGauge, UsageHold
    from sm_billing.plans import seed_default_plan

    monkeypatch.setattr(billing, "billing_installed", lambda: True)
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = state.session_factory
    await seed_default_plan(factory)
    try:
        first = await billing.reserve(factory, "t1", 100, billing.hold_key("img", 0))
        await billing.settle(factory, first, None)
        second = await billing.reserve(factory, "t1", 150, billing.hold_key("img", "a1"))
        await billing.settle(factory, second, first)
        async with factory() as s:
            holds = dict((await s.execute(select(UsageHold.id, UsageHold.status))).all())
            level = (await s.execute(select(UsageGauge.in_use))).scalar_one()
        assert holds == {first: "released", second: "committed"} and level == 150
        await billing.release(factory, [second])
        async with factory() as s:
            assert (await s.execute(select(UsageGauge.in_use))).scalar_one() == 0
    finally:
        await state.engine.dispose()
