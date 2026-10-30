"""URL imports: ``images.download_items`` and the three-layer dedupe.

Ports of the portal's ``test_import_dedup`` and ``test_download_task_idempotency``
cases. Downloads go through the real ``safe_stream`` over the fake resolver and
connection layer of :mod:`tests.support.fetch`.
"""

from __future__ import annotations

import httpx
import pytest
from sm_images.imports import download, launch, retrying
from sm_images.imports.features import url_external_id
from sm_images.ingest import dedupe
from sm_images.models import Image
from sm_images.tenancy import DEFAULT_TENANT

from tests.support.fetch import body
from tests.support.imports import HOST, URL, feature, serve_images
from tests.support.pipeline import jpeg

pytestmark = pytest.mark.asyncio


def url(name: str) -> str:
    return f"https://{HOST}/{name}"


def paths(seen) -> list[str]:
    return [r.url.path for r in seen]


@pytest.fixture
def no_sleep(monkeypatch):
    waits: list[float] = []

    async def fake(seconds):
        waits.append(seconds)

    monkeypatch.setattr(retrying, "_sleep", fake)
    return waits


@pytest.fixture
def broker(monkeypatch):
    """Downloads are recorded, not run: what a broker-backed runner leaves behind."""
    sent: list[list[int]] = []

    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append(list(ids))

    monkeypatch.setattr(launch, "launch_downloads", fake)
    return sent


async def _existing(imp, external_id: str, coll=None, source: str = "import") -> Image:
    coll = coll or imp.coll
    image_id = await imp.pipe.image(coll, external_source=source, external_id=external_id)
    return await imp.pipe.row(image_id)


async def test_url_import_downloads_and_completes(imp, resolver, inner):
    seen = serve_images(resolver, inner)
    job = await imp.job(
        [
            feature({"url": url("p/A1.jpg")}, (1.0, 2.0)),
            feature({"nope": 1}),
            feature({"url": url("b.jpg")}),
        ],
        URL,
    )
    assert await imp.run(job) == "completed"
    assert sorted(paths(seen)) == ["/b.jpg", "/p/A1.jpg"]
    assert await imp.statuses(job) == ["done", "failed", "done"]
    assert await imp.counts(job) == ("completed", 3, 3, 2, 0, 1)
    images = {i.external_id: i for i in await imp.images()}
    first = images[url_external_id(url("p/A1.jpg"))]
    assert (first.filename, first.lat, first.lng, first.external_source) == (
        "A1.jpg",
        2.0,
        1.0,
        "import",
    )


async def test_three_layer_dedupe(imp, resolver, inner):
    seen = serve_images(resolver, inner)
    known = await _existing(imp, url_external_id(url("known.jpg")))
    trashed = await _existing(imp, url_external_id(url("trashed.jpg")))
    await imp.pipe.trash(Image, trashed.id)
    other = await imp.pipe.collection({})
    await _existing(imp, url_external_id(url("elsewhere.jpg")), coll=other)
    await _existing(imp, url_external_id(url("upload.jpg")), source="upload")
    feats = [
        feature({"url": url("twice.jpg")}),
        feature({"url": url("known.jpg")}),
        feature({"url": url("twice.jpg")}),  # layer 1: earlier in this file
        feature({"url": url("trashed.jpg")}),  # a trashed image is still a duplicate
        feature({"url": url("elsewhere.jpg")}),  # another collection: not a duplicate
        feature({"url": url("upload.jpg")}),  # another source: not a duplicate
    ]
    job = await imp.job(feats, URL)
    assert await imp.run(job) == "completed"
    assert sorted(paths(seen)) == ["/elsewhere.jpg", "/twice.jpg", "/upload.jpg"]
    items = await imp.items(job)
    assert [i.status.value for i in items] == [
        "done",
        "duplicate",
        "duplicate",
        "duplicate",
        "done",
        "done",
    ]
    assert (items[1].image_id, items[3].image_id) == (known.id, trashed.id)
    assert await imp.counts(job) == ("completed", 6, 6, 3, 3, 0)
    trashed_again = [i for i in await imp.images() if i.id == trashed.id]
    assert trashed_again[0].is_deleted  # reported as a duplicate, not restored


async def test_layer_one_spans_chunks(imp, resolver, inner, monkeypatch):
    from sm_images.imports import runner

    monkeypatch.setattr(runner, "CHUNK", 1)
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": url("a.jpg")}), feature({"url": url("a.jpg")})], URL)
    assert await imp.run(job) == "completed"
    assert paths(seen) == ["/a.jpg"]
    assert await imp.statuses(job) == ["done", "duplicate"]


async def test_existing_image_is_deduped_before_anything_is_downloaded(
    imp, resolver, inner, broker
):
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": url("late.jpg")})], URL)
    assert await imp.run(job) == "running"  # its download is queued, not run
    late = await _existing(imp, url_external_id(url("late.jpg")))
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, job.generation, broker[0]
    )
    assert seen == []
    (item,) = await imp.items(job)
    assert (item.status.value, item.image_id) == ("duplicate", late.id)
    assert (await imp.counts(job))[0] == "completed"


async def test_duplicate_image_at_commit_is_treated_as_dedup_not_failure(
    imp, resolver, inner, broker, monkeypatch
):
    serve_images(resolver, inner)
    job = await imp.job([feature({"url": url("race.jpg")})], URL)
    await imp.run(job)
    winner = await _existing(imp, url_external_id(url("race.jpg")))
    real, calls = dedupe.find_external, {"n": 0}

    async def blind_twice(*args):
        calls["n"] += 1
        return None if calls["n"] <= 2 else await real(*args)

    monkeypatch.setattr(dedupe, "find_external", blind_twice)
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, job.generation, broker[0]
    )
    (item,) = await imp.items(job)
    assert (item.status.value, item.image_id) == ("duplicate", winner.id)
    assert [i.id for i in await imp.images()] == [winner.id]
    assert [k for k in imp.stored() if "original" in k] == [winner.storage_key]


async def test_download_idempotent(imp, resolver, inner, broker):
    """Redelivery of a settled item, an item a restart deleted, a paused job."""
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": url("a.jpg")}), feature({"url": url("b.jpg")})], URL)
    await imp.run(job)
    ids = broker[0]
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, job.generation, ids[:1]
    )
    before = await imp.counts(job)
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, job.generation, ids[:1]
    )
    await download.download_items_async(
        imp.runtime, DEFAULT_TENANT, job.id, job.generation, [999_999]
    )
    assert await imp.counts(job) == before
    assert paths(seen) == ["/a.jpg"]

    from sm_images.imports import controls

    await controls.pause(imp.runtime, DEFAULT_TENANT, job.id)
    await download.download_items_async(imp.runtime, DEFAULT_TENANT, job.id, job.generation, ids)
    assert paths(seen) == ["/a.jpg"]  # a paused job downloads nothing
    assert await imp.statuses(job) == ["done", "pending"]


async def test_retryable_answers_are_retried_with_backoff(imp, resolver, inner, no_sleep):
    flaky = {"n": 0}

    def once_503(request):
        flaky["n"] += 1
        return httpx.Response(503) if flaky["n"] == 1 else body(jpeg())

    serve_images(resolver, inner, fail={"/flaky.jpg": once_503})
    job = await imp.job([feature({"url": url("flaky.jpg")})], URL)
    assert await imp.run(job) == "completed"
    (item,) = await imp.items(job)
    assert (item.status.value, item.attempts) == ("done", 2)
    assert len(no_sleep) == 1


async def test_permanent_failures_are_not_retried(imp, resolver, inner, no_sleep):
    resolver["inside.example"] = ["10.0.0.5"]
    seen = serve_images(
        resolver,
        inner,
        fail={
            "/gone.jpg": httpx.Response(404),
            "/page.jpg": body(b"<html>not an image</html>"),
            "/huge.jpg": httpx.Response(200, headers={"content-length": str(10**9)}),
        },
    )
    feats = [
        feature({"url": url("gone.jpg")}),
        feature({"url": url("page.jpg")}),
        feature({"url": url("huge.jpg")}),
        feature({"url": "http://inside.example/x.jpg"}),
    ]
    job = await imp.job(feats, URL)
    assert await imp.run(job) == "completed"
    items = await imp.items(job)
    assert [i.last_error for i in items] == [
        "http_404",
        "unsupported_type",
        "too_large",
        "unsafe_url",
    ]
    assert [i.attempts for i in items] == [1, 1, 1, 1]
    assert no_sleep == [] and len(seen) == 3
    assert await imp.counts(job) == ("completed", 4, 4, 0, 0, 4)


async def test_a_long_retry_after_defers_the_item(imp, resolver, inner, no_sleep):
    serve_images(
        resolver, inner, fail={"/busy.jpg": httpx.Response(429, headers={"retry-after": "3600"})}
    )
    job = await imp.job([feature({"url": url("busy.jpg")})], URL)
    assert await imp.run(job) == "running"
    (item,) = await imp.items(job)
    assert (item.status.value, item.attempts, item.last_error) == ("pending", 1, "http_429")
    assert no_sleep == []  # never waited less than the server asked
