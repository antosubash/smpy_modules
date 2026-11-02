"""The web pre-checks read the collection owner's headroom (#284).

In billing's ``user`` mode the quota is the owner's, so an upload by anyone with
edit rights is checked against ``user:<owner>``, never the uploader's own
subject. The open-upload count and the admission lock stay per tenant.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.core import constants
from sm_images.models import Collection
from sm_images.module import ImagesModule

from tests.ingest.test_upload_base64 import b64, post
from tests.support.access import share
from tests.support.stub_auth import as_user, user_uuid
from tests.support.upload import BASE, OLGA, jpeg, make_collection

OWNER = f"user:{user_uuid('olga')}"
EDDIE = as_user("eddie", ("images.view", "images.create"))
QUOTA = constants.CODE_QUOTA_EXCEEDED


@pytest_asyncio.fixture
async def api(uploads, gauge):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.app.state.billing_usage = gauge
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    return uploads


@pytest.fixture
def web_user(api, user_mode):
    user_mode.web(api.app)
    return api


def _checks(gauge) -> list[str]:
    return [c[1] for c in gauge.calls if c[0] == "check"]


async def _share_to_eddie(api) -> None:
    from sqlalchemy import select

    async with api.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalar_one()
        s.add(share(coll, "eddie", "edit"))
        await s.commit()


async def test_precheck_reads_owner_subject(web_user, gauge):
    done = await post(web_user, web_user.cid, filename="a.jpg", data=b64(jpeg(size=(64, 48))))
    assert done.status_code == 200, done.text
    assert _checks(gauge) == [OWNER]


async def test_tenant_mode_precheck_unchanged(api, gauge):
    done = await post(api, api.cid, filename="a.jpg", data=b64(jpeg(size=(64, 48))))
    assert done.status_code == 200, done.text
    assert _checks(gauge) == ["default"]


async def test_shared_uploader_is_checked_against_owner_quota(web_user, gauge):
    await _share_to_eddie(web_user)
    gauge.limits = {OWNER: 10}  # the owner is full; eddie's own subject has no limit
    got = await web_user.post(
        f"{BASE}/{web_user.cid}/images/base64",
        json={"filename": "a.jpg", "data": b64(jpeg(size=(64, 48)))},
        headers=EDDIE,
    )
    assert (got.status_code, got.json()["code"]) == (402, QUOTA)
    assert _checks(gauge) == [OWNER]


async def test_direct_upload_admission_reads_owner_headroom(web_user, gauge):
    gauge.limits = {OWNER: 10}
    got = await web_user.post(
        f"{BASE}/{web_user.cid}/uploads", json={"filename": "big.jpg", "size": 100}, headers=OLGA
    )
    assert (got.status_code, got.json()["code"]) == (402, QUOTA)
    assert _checks(gauge) == [OWNER]


async def test_zip_admission_reads_owner_headroom(web_user, gauge):
    gauge.limits = {OWNER: 10}
    got = await web_user.post(
        f"{BASE}/{web_user.cid}/imports/zip",
        json={"filename": "p.zip", "size": 100},
        headers=OLGA,
    )
    assert (got.status_code, got.json()["code"]) == (402, QUOTA)
    assert _checks(gauge) == [OWNER]


async def test_import_precheck_reads_owner_subject(web_user, gauge):
    gauge.limits = {OWNER: 0}
    got = await web_user.post(
        f"{BASE}/{web_user.cid}/imports",
        data={"kind": "geojson_base64", "mapping": '{"image_prop": "img"}'},
        files={"file": ("p.geojson", b'{"type":"FeatureCollection","features":[]}', "text/plain")},
        headers=OLGA,
    )
    assert (got.status_code, got.json()["code"]) == (402, QUOTA)
    assert _checks(gauge) == [OWNER]


async def test_admission_cap_stays_per_tenant(web_user, gauge):
    """Another user's open upload still counts against the tenant's cap."""
    await _share_to_eddie(web_user)
    web_user.app.state.sm_images.settings.max_open_uploads_per_tenant = 1
    url = f"{BASE}/{web_user.cid}/uploads"
    first = await web_user.post(url, json={"filename": "a.jpg", "size": 50}, headers=OLGA)
    assert first.status_code == 201, first.text
    second = await web_user.post(url, json={"filename": "b.jpg", "size": 50}, headers=EDDIE)
    assert second.status_code == 429
