"""The ZIP routes: open the job and its upload, relay the parts, extract.

The filesystem backend cannot presign, so the parts go through the app's relay
route - the same one a direct image upload uses. Once ``extract`` sealed the
archive, the upload takes nothing more: a part or a complete is a 409.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.core import constants
from sm_images.models import ImportJob
from sm_images.module import ImagesModule

from tests.support.pipeline import jpeg
from tests.support.stub_auth import as_user
from tests.support.upload import OLGA, all_rows, make_collection, stored
from tests.support.zip import make_zip

pytestmark = pytest.mark.asyncio
SAM = as_user("sam", ("images.view", "images.create"))
UPLOADS = "/api/images/uploads"


@pytest_asyncio.fixture
async def api(uploads, monkeypatch):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)  # several parts
    return uploads


def _archive() -> bytes:
    return make_zip([(f"{c}.jpg", jpeg((16, 12), c)) for c in ("red", "blue", "green")])


async def _open(api, data: bytes, headers=OLGA, **body):
    body = {"filename": "photos.zip", "size": len(data), **body}
    return await api.post(
        f"/api/images/collections/{api.cid}/imports/zip", json=body, headers=headers
    )


async def _send(api, upload: dict, data: bytes) -> list[dict]:
    size, parts = upload["part_size"], []
    for n, url in enumerate(upload["part_urls"], start=1):
        put = await api.put(url, content=data[(n - 1) * size : n * size], headers=OLGA)
        assert put.status_code == 200, put.text
        parts.append({"no": n, "etag": put.json()["etag"]})
    return parts


async def test_zip_upload_relay_and_extract(api):
    data = _archive()
    opened = await _open(api, data)
    assert opened.status_code == 201, opened.text
    created = opened.json()
    upload = created["upload"]
    assert upload["direct"] is False and len(upload["part_urls"]) > 1
    job = (await api.get(f"/api/images/imports/{created['job_id']}", headers=OLGA)).json()
    assert (job["kind"], job["status"]) == ("zip", "uploading")

    parts = await _send(api, upload, data)
    url = f"/api/images/imports/{created['job_id']}/extract"
    got = await api.post(url, json={"parts": parts}, headers=OLGA)
    assert got.status_code == 202, got.text
    assert (got.json()["status"], got.json()["done_count"]) == ("completed", 3)
    assert "source_etag" not in got.json() and "upload_session_id" not in got.json()
    assert not [k for k in stored(api.storage) if "/imports/" in k]  # released on completion

    # Sealed: nothing more goes into that upload.
    again = await api.put(upload["part_urls"][0], content=data[:400], headers=OLGA)
    assert (again.status_code, again.json()["code"]) == (409, "upload_not_open")
    done = await api.post(f"{UPLOADS}/{upload['upload_id']}/complete", json={}, headers=OLGA)
    assert (done.status_code, done.json()["code"]) == (409, "upload_not_open")
    twice = await api.post(url, json={}, headers=OLGA)
    assert (twice.status_code, twice.json()["code"]) == (409, "already_sealed")


async def test_a_zip_upload_is_never_completed_as_an_image(api):
    data = _archive()
    upload = (await _open(api, data)).json()["upload"]
    parts = await _send(api, upload, data)
    got = await api.post(
        f"{UPLOADS}/{upload['upload_id']}/complete", json={"parts": parts}, headers=OLGA
    )
    assert (got.status_code, got.json()["code"]) == (409, "upload_not_open")


async def test_missing_parts_hand_the_upload_back(api):
    data = _archive()
    created = (await _open(api, data)).json()
    url = f"/api/images/imports/{created['job_id']}/extract"
    got = await api.post(url, json={}, headers=OLGA)
    assert (got.status_code, got.json()["code"]) == (409, "parts_mismatch")
    await _send(api, created["upload"], data)  # still open: the client can finish
    assert (await api.post(url, json={}, headers=OLGA)).json()["status"] == "completed"


async def test_strangers_and_bad_requests(api):
    data = _archive()
    assert (await _open(api, data, headers=SAM)).status_code == 404
    created = (await _open(api, data)).json()
    url = f"/api/images/imports/{created['job_id']}/extract"
    assert (await api.post(url, json={}, headers=SAM)).status_code == 404

    getattr(api.app.state, constants.PACKAGE).settings.zip_max_bytes = 10
    too_big = await _open(api, data)
    assert (too_big.status_code, too_big.json()["code"]) == (413, "file_too_large")
    bad = await _open(api, b"x" * 5, mapping={"url_prop": "u"})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_mapping")
    assert len(await all_rows(api, ImportJob)) == 1


async def test_the_geojson_route_still_refuses_kind_zip(api):
    got = await api.post(
        f"/api/images/collections/{api.cid}/imports",
        data={"kind": "zip", "mapping": "{}"},
        files={"file": ("a.zip", b"{}", "application/zip")},
        headers=OLGA,
    )
    assert (got.status_code, got.json()["code"]) == (422, "unsupported_kind")
