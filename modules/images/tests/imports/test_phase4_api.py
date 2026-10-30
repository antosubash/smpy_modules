"""Phase 4 review fixes over HTTP: a job records whose right it runs under
(and a control hands it to whoever used it), and trashing a collection
cancels its unfinished imports in the same transaction."""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from sm_images.imports import access
from sm_images.models import ImportJob
from sm_images.models.enums import ImportKind, JobStatus
from sm_images.module import ImagesModule

from tests.support.access import share
from tests.support.imports import b64, feature, geojson
from tests.support.pipeline import jpeg
from tests.support.stub_auth import as_user, user_uuid
from tests.support.upload import OLGA, WRITER, all_rows, make_collection
from tests.support.zip import make_zip

pytestmark = pytest.mark.asyncio
EDDIE = as_user("eddie", WRITER)
MAX = as_user("max", (*WRITER, "images.manage"))
B64_MAPPING = json.dumps({"image_prop": "img"})


@pytest_asyncio.fixture
async def api(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    return uploads


async def _start(api, headers, img: str | None = None):
    doc = geojson([feature({"img": img or b64()})])
    files = {"file": ("p.geojson", doc, "application/geo+json")}
    data = {"kind": "geojson_base64", "mapping": B64_MAPPING}
    got = await api.post(
        f"/api/images/collections/{api.cid}/imports", data=data, files=files, headers=headers
    )
    assert got.status_code == 202, got.text
    return got.json()["id"]


async def _job(api, job_id) -> ImportJob:
    (row,) = [r for r in await all_rows(api, ImportJob) if str(r.id) == str(job_id)]
    return row


async def _share_eddie(api) -> None:
    from sm_images.models import Collection

    async with api.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(api.cid))
        s.add(share(coll, "eddie", "edit"))
        await s.commit()


async def test_a_job_records_whose_right_it_runs_under(api):
    await _share_eddie(api)
    for headers, who, basis in (
        (OLGA, "olga", access.OWNER),
        (EDDIE, "eddie", access.SHARE),
        (MAX, "max", access.MANAGE),
    ):
        row = await _job(api, await _start(api, headers))
        assert (row.run_as, row.access_basis) == (user_uuid(who), basis), who
        assert row.created_by == user_uuid(who)


async def test_a_restart_runs_under_whoever_restarted_it(api):
    await _share_eddie(api)
    job_id = await _start(api, EDDIE, img="@@@")  # fails: the source is kept for a retry
    got = await api.post(f"/api/images/imports/{job_id}/restart", headers=OLGA)
    assert got.status_code == 202, got.text
    row = await _job(api, job_id)
    assert (row.run_as, row.access_basis) == (user_uuid("olga"), access.OWNER)
    assert row.created_by == user_uuid("eddie")  # the audit column keeps the creator


async def test_trashing_a_collection_cancels_its_unfinished_imports(api):
    async with api.db_state.session_factory() as s:
        for status in (JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.COMPLETED):
            s.add(
                ImportJob(
                    collection_id=uuid.UUID(api.cid),
                    kind=ImportKind.GEOJSON_BASE64,
                    status=status,
                    generation=3,
                    tenant_id="default",
                )
            )
        await s.commit()
    got = await api.delete(f"/api/images/collections/{api.cid}", headers=OLGA)
    assert got.status_code == 204, got.text
    rows = {r.status: r for r in await all_rows(api, ImportJob)}
    assert set(rows) == {JobStatus.CANCELLED, JobStatus.COMPLETED}
    cancelled = [r for r in await all_rows(api, ImportJob) if r.status is JobStatus.CANCELLED]
    assert [r.generation for r in cancelled] == [4, 4]
    assert rows[JobStatus.COMPLETED].generation == 3


async def test_the_zip_extractor_takes_the_job_over(api):
    await _share_eddie(api)
    data = make_zip([("a.jpg", jpeg((16, 12), "red"))])
    body = {"filename": "a.zip", "size": len(data)}
    opened = await api.post(
        f"/api/images/collections/{api.cid}/imports/zip", json=body, headers=OLGA
    )
    assert opened.status_code == 201, opened.text
    created = opened.json()
    upload, parts = created["upload"], []
    size = upload["part_size"]
    for n, url in enumerate(upload["part_urls"], start=1):
        put = await api.put(url, content=data[(n - 1) * size : n * size], headers=OLGA)
        parts.append({"no": n, "etag": put.json()["etag"]})
    url = f"/api/images/imports/{created['job_id']}/extract"
    got = await api.post(url, json={"parts": parts}, headers=EDDIE)
    assert got.status_code == 202, got.text
    assert got.json()["status"] == "completed"
    row = await _job(api, created["job_id"])
    assert (row.run_as, row.access_basis) == (user_uuid("eddie"), access.SHARE)
    assert row.created_by == user_uuid("olga")
