"""The ingest hold bills the collection's owner in billing's ``user`` mode (#284).

The web path reads the mode through ``subject.runtime_mode()`` (the global
runtime ``on_startup`` installs), an import through the runtime its task binds.
The image row records the subject its hold was taken under, and so does the
``ingest`` op.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.core.billing import subject
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import Collection

from tests.ingest.test_upload_base64 import b64, post
from tests.support.billing import ops
from tests.support.imports import b64 as import_b64
from tests.support.imports import feature
from tests.support.stub_auth import user_uuid
from tests.support.upload import all_rows, jpeg, make_collection, post_files

OLGA = f"user:{user_uuid('olga')}"


@pytest.fixture
def web_user_mode(user_mode):
    return user_mode.web()


async def _upload(uploads) -> None:
    cid = await make_collection(uploads)
    (coll,) = await all_rows(uploads, Collection)
    assert f"user:{coll.owner_id}" == OLGA  # the uploader owns it
    done = await post(uploads, cid, filename="a.jpg", data=b64(jpeg(size=(64, 48))))
    assert done.status_code == 200, done.text


async def test_upload_in_user_mode_holds_under_owner(uploads, gauge, web_user_mode):
    await _upload(uploads)
    (hold,) = gauge.live()
    assert hold.tenant_id == OLGA
    assert gauge.level_of(DEFAULT_TENANT) == 0
    (row,) = await all_rows(uploads)
    assert (row.storage_hold_id, row.storage_subject) == (hold.id, OLGA)
    (op,) = await ops(uploads.db_state)
    assert (op.op, op.subject) == ("ingest", OLGA)


async def test_upload_in_tenant_mode_unchanged(uploads, gauge):
    await _upload(uploads)
    (hold,) = gauge.live()
    assert hold.tenant_id == DEFAULT_TENANT
    (row,) = await all_rows(uploads)
    # recorded explicitly, as settle/install do (``NULL`` would mean the same)
    assert (row.storage_hold_id, row.storage_subject) == (hold.id, DEFAULT_TENANT)
    (op,) = await ops(uploads.db_state)
    assert op.subject == DEFAULT_TENANT


async def test_upload_without_billing_records_no_subject(uploads):
    await _upload(uploads)
    (row,) = await all_rows(uploads)
    assert (row.storage_hold_id, row.storage_subject) == (None, None)


async def test_upload_to_unbillable_owner_bills_tenant(
    uploads, gauge, web_user_mode, monkeypatch, caplog
):
    async def gone(db, who):
        return False

    monkeypatch.setattr(subject, "user_exists", gone)
    subject.reset_unbillable_log()
    with caplog.at_level("WARNING"):
        await _upload(uploads)
    (hold,) = gauge.live()
    assert hold.tenant_id == DEFAULT_TENANT
    (row,) = await all_rows(uploads)
    assert row.storage_subject == DEFAULT_TENANT
    logged = [r for r in caplog.records if "images.billing.owner_unbillable" in r.getMessage()]
    assert len(logged) == 1


async def test_import_item_in_user_mode_holds_under_owner(imp, gauge, user_mode):
    owner = str(uuid.uuid4())
    coll = await imp.pipe.collection({}, slug="owned", owner_id=owner)
    imp.pipe.runtime = user_mode.runtime(imp.pipe.runtime)  # the task binds it
    job = await imp.job([feature({"img": import_b64("red")})], coll=coll)
    assert await imp.run(job) == "completed"
    (image,) = await imp.images(coll)
    (hold,) = gauge.live()
    assert hold.tenant_id == f"user:{owner}"
    assert (image.storage_hold_id, image.storage_subject) == (hold.id, f"user:{owner}")


async def test_multi_file_reserve_looks_the_owner_up_once(
    uploads, gauge, web_user_mode, monkeypatch
):
    seen: list[str] = []

    async def exists(db, who):
        seen.append(who)
        return True

    monkeypatch.setattr(subject, "user_exists", exists)
    cid = await make_collection(uploads)
    files = [(f"{n}.jpg", jpeg(size=(64 + n, 48)), "image/jpeg") for n in range(3)]
    done = await post_files(uploads, cid, files)
    assert done.status_code == 200, done.text
    assert seen == [OLGA]  # one lookup for the three slots
    holds = gauge.live()
    assert [h.tenant_id for h in holds] == [OLGA] * 3
    assert {r.storage_subject for r in await all_rows(uploads)} == {OLGA}
