"""The import routes: start (file or source URL), list, read, controls, delete.

Eager, as the harness's Celery is: a 202 comes back with the import already run.
"""

from __future__ import annotations

import json
import socket

import pytest
import pytest_asyncio
from sm_images import constants
from sm_images.models import ImportJob
from sm_images.module import ImagesModule

from tests.support.fetch import PUBLIC_IP, body, fake_dns
from tests.support.imports import HOST, b64, feature, geojson, serve_images
from tests.support.stub_auth import as_user
from tests.support.upload import OLGA, all_rows, make_collection, stored

pytestmark = pytest.mark.asyncio
SAM = as_user("sam", ("images.view", "images.create"))
B64_MAPPING = json.dumps({"image_prop": "img"})


@pytest_asyncio.fixture
async def api(uploads):
    ImagesModule._use_runtime(uploads.app, uploads.db_state.session_factory)
    uploads.cid = await make_collection(uploads)  # type: ignore[attr-defined]
    return uploads


def _settings(api):
    return getattr(api.app.state, constants.PACKAGE).settings


async def _start(api, *, file: bytes | None = None, headers=OLGA, **data):
    data.setdefault("kind", "geojson_base64")
    data.setdefault("mapping", B64_MAPPING)
    files = {"file": ("points.geojson", file, "application/geo+json")} if file is not None else None
    return await api.post(
        f"/api/images/collections/{api.cid}/imports", data=data, files=files, headers=headers
    )


async def test_upload_import_runs_and_is_listed(api):
    doc = geojson([feature({"img": b64("red")}, (8.5, 47.3)), feature({"img": b64("blue")})])
    got = await _start(api, file=doc)
    assert got.status_code == 202, got.text
    job = got.json()
    assert (job["status"], job["total_count"], job["done_count"]) == ("completed", 2, 2)
    assert "source_key" not in job and "staged_keys" not in job and "created_by" not in job
    listed = await api.get(f"/api/images/collections/{api.cid}/imports", headers=OLGA)
    assert [j["id"] for j in listed.json()["items"]] == [job["id"]]
    one = await api.get(f"/api/images/imports/{job['id']}", headers=OLGA)
    assert one.json()["done_count"] == 2
    assert not [k for k in stored(api.storage) if "/imports/" in k]


async def test_a_stranger_cannot_start_read_or_control_an_import(api):
    assert (await _start(api, file=geojson([]), headers=SAM)).status_code == 404
    job = (await _start(api, file=geojson([]))).json()
    for method, tail in (("GET", ""), ("POST", "/pause"), ("POST", "/restart"), ("DELETE", "")):
        got = await api.request(method, f"/api/images/imports/{job['id']}{tail}", headers=SAM)
        assert got.status_code == 404, (method, tail)


@pytest.mark.parametrize(
    ("data", "file", "code"),
    [
        ({"kind": "zip"}, b"{}", "unsupported_kind"),
        ({"kind": "nope"}, b"{}", "invalid_import_kind"),
        ({"kind": "geojson_url", "mapping": "{}"}, b"{}", "url_prop_required"),
        ({"mapping": '{"image_prop": "i", "extra": 1}'}, b"{}", "invalid_mapping"),
        (
            {"mapping": '{"image_prop": "i", "filename_pattern": "(?P<x>a)"}'},
            b"{}",
            "invalid_mapping",
        ),
        ({}, None, "source_required"),
        ({"source_url": "https://example.org/a.geojson"}, b"{}", "source_required"),
        ({}, b'{"type": "FeatureCollection", "features": [{"a"', "invalid_json"),
        ({}, b'{"type": "Feature"}', "not_feature_collection"),
    ],
)
async def test_bad_requests_are_refused_before_a_job_exists(api, data, file, code):
    got = await _start(api, file=file, **data)
    assert (got.status_code, got.json().get("code")) == (422, code), got.text
    assert await all_rows(api, ImportJob) == []


async def test_feature_limit(api):
    _settings(api).geojson_max_features = 2
    got = await _start(api, file=geojson([feature({"img": b64()}) for _ in range(3)]))
    assert (got.status_code, got.json()["code"]) == (422, "too_many_features")
    assert await all_rows(api, ImportJob) == []
    assert stored(api.storage) == []


async def test_source_url_ssrf_rejected(api, resolver, inner):
    resolver["evil.example"] = ["10.0.0.5"]
    seen = inner(lambda r: body(b"{}"))
    for url in (
        "http://evil.example/a.geojson",
        "http://169.254.169.254/latest",
        "file:///etc/passwd",
    ):
        got = await _start(api, kind="geojson_url", mapping='{"url_prop": "u"}', source_url=url)
        assert (got.status_code, got.json()["code"]) == (422, "unsafe_source_url"), url
    assert seen == [] and await all_rows(api, ImportJob) == []


async def test_dns_rebinding_on_the_source_fetch_fails_the_job(api, monkeypatch, inner):
    answers = iter([PUBLIC_IP, "127.0.0.1"])

    def flip(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(answers, "127.0.0.1"), port))]

    fake_dns(monkeypatch, flip)
    seen = inner(lambda r: body(b"{}"))
    got = await _start(
        api,
        kind="geojson_url",
        mapping='{"url_prop": "u"}',
        source_url="http://src.example/a.geojson",
    )
    assert got.status_code == 202, got.text
    job = got.json()
    assert job["status"] == "failed" and job["errors"][0]["code"] == "unsafe_source_url"
    assert seen == [] and stored(api.storage) == []


async def test_source_url_import_downloads_its_images(api, resolver, inner):
    doc = geojson(
        [feature({"u": f"https://{HOST}/a.jpg"}), feature({"u": f"https://{HOST}/b.jpg"})]
    )
    resolver["src.example"] = [PUBLIC_IP]
    serve_images(resolver, inner, fail={"/points.geojson": lambda r: body(doc)})
    got = await _start(
        api,
        kind="geojson_url",
        mapping='{"url_prop": "u"}',
        source_url="https://src.example/points.geojson",
    )
    job = got.json()
    assert (job["status"], job["total_count"], job["done_count"]) == ("completed", 2, 2), job
    assert job["source_url"] == "https://src.example/points.geojson"


async def test_controls_over_http(api):
    job = (await _start(api, file=geojson([feature({"img": "!!"})]))).json()
    assert job["failed_count"] == 1
    url = f"/api/images/imports/{job['id']}"
    paused = await api.post(f"{url}/pause", headers=OLGA)
    assert (paused.status_code, paused.json()["code"]) == (409, "job_not_active")
    # A finished base64 job with failures keeps its source: retry-failed works.
    retried = await api.post(f"{url}/retry-failed", headers=OLGA)
    assert retried.status_code == 202, retried.text
    assert (retried.json()["status"], retried.json()["failed_count"]) == ("completed", 1)
    resumed = await api.post(f"{url}/resume", headers=OLGA)
    assert resumed.status_code == 409
    assert (await api.delete(url, headers=OLGA)).status_code == 204
    assert (await api.get(url, headers=OLGA)).status_code == 404
