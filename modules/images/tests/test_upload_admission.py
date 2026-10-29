"""Opening a direct or ZIP upload is admitted against what is already open (S2).

An upload session is a capability: the parts go straight to storage, and the
quota is only enforced when ``complete`` takes the hold. Before this a tenant
over quota could still open sessions and fill them. ``start`` now refuses when
the gauge plus the declared sizes of the tenant's still-open sessions plus this
one would not fit the plan (402 ``quota_exceeded``), and past
``max_open_uploads_per_tenant`` open sessions (429 ``too_many_open_uploads``).
Soft: two concurrent opens can each see the other missing, so the overshoot is
at most the cap's worth of declared sizes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sm_images import constants
from sm_images.models import UploadSession
from sm_images.module import ImagesModule
from sqlalchemy import update

from tests.upload_support import BASE, OLGA, make_collection

QUOTA = constants.CODE_QUOTA_EXCEEDED
TOO_MANY = constants.CODE_TOO_MANY_OPEN_UPLOADS
UPLOADS = "/api/images/uploads"


@pytest_asyncio.fixture
async def api(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    return uploads


def _multipart_uploads(api) -> int:
    """Open multipart uploads in the filesystem backend's staging area."""
    from pathlib import Path

    root = Path(api.storage.root)
    return sum(1 for p in root.rglob("*") if p.is_dir() and p.parent.name == ".multipart")


async def _image(api, size: int):
    body = {"filename": "big.jpg", "size": size}
    return await api.post(f"{BASE}/{api.cid}/uploads", json=body, headers=OLGA)


async def _zip(api, size: int):
    body = {"filename": "photos.zip", "size": size}
    return await api.post(f"{BASE}/{api.cid}/imports/zip", json=body, headers=OLGA)


async def test_open_sessions_count_against_the_quota(api, gauge):
    api.app.state.billing_usage = gauge
    gauge.limit = 1000
    first = await _image(api, 600)
    assert first.status_code == 201, first.text
    second = await _image(api, 600)  # 600 open + 600 > 1000
    assert second.status_code == 402, second.text
    assert second.json()["code"] == QUOTA
    zipped = await _zip(api, 600)
    assert zipped.status_code == 402, zipped.text
    assert (await _image(api, 400)).status_code == 201  # 600 + 400 fits exactly
    aborted = await api.delete(f"{UPLOADS}/{first.json()['upload_id']}", headers=OLGA)
    assert aborted.status_code == 204
    assert (await _image(api, 600)).status_code == 201  # the aborted one no longer counts


async def test_an_expired_session_no_longer_counts(api, gauge):
    api.app.state.billing_usage = gauge
    gauge.limit = 1000
    assert (await _image(api, 900)).status_code == 201
    async with api.db_state.session_factory() as s:
        past = datetime.now(UTC) - timedelta(seconds=1)
        await s.execute(update(UploadSession).values(expires_at=past))
        await s.commit()
    assert (await _image(api, 900)).status_code == 201


@pytest.mark.parametrize("opener", [_image, _zip])
async def test_the_open_session_cap(api, opener):
    api.app.state.sm_images.settings.max_open_uploads_per_tenant = 2
    assert (await _image(api, 10)).status_code == 201
    assert (await _zip(api, 10)).status_code == 201
    staged = _multipart_uploads(api)
    assert staged == 2
    refused = await opener(api, 10)
    assert refused.status_code == 429, refused.text
    assert refused.json()["code"] == TOO_MANY
    assert _multipart_uploads(api) == staged  # the refused one's backend upload is aborted


def test_the_cap_defaults_to_twenty():
    from sm_images.settings import ImagesSettings

    assert ImagesSettings.model_fields["max_open_uploads_per_tenant"].default == 20


async def test_without_billing_only_the_cap_applies(api):
    big = api.app.state.sm_images.settings.max_image_bytes
    for _ in range(3):
        assert (await _image(api, big)).status_code == 201
