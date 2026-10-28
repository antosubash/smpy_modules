"""Review round 1: items 7-12 of the fix brief (oversized features, retry of
parse failures, broker-mode resume, source retention, heartbeats)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sm_images.errors import Conflict
from sm_images.imports import beat, controls, jobs, launch, runner, staging
from sm_images.imports.geojson_stream import OVERSIZE, iter_features
from sm_images.imports.mapping import Mapping
from sm_images.tenancy import DEFAULT_TENANT

from tests.fetch_support import PUBLIC_IP, body
from tests.import_support import HOST, URL, b64, feature, geojson, serve_images

T = DEFAULT_TENANT


# -- 7. a feature over the byte budget fails alone ---------------------------------


def test_an_oversized_feature_is_never_built():
    doc = geojson([{"p": "x" * 500}, {"p": "small"}, "bare"])
    got = list(iter_features(io.BytesIO(doc), 0, max_feature_bytes=100))
    assert got == [(0, OVERSIZE), (1, {"p": "small"}), (2, "bare")]
    resumed = list(iter_features(io.BytesIO(doc), 1, max_feature_bytes=100))
    assert [i for i, _ in resumed] == [1, 2]


async def test_an_oversized_feature_fails_and_the_import_goes_on(imp):
    imp.pipe.settings.geojson_max_feature_bytes = 4000
    feats = [feature({"img": b64(size=(400, 400))}), feature({"img": b64()})]
    job = await imp.job(feats)
    assert await imp.run(job) == "completed"
    items = await imp.items(job)
    assert [(i.status.value, i.last_error) for i in items] == [
        ("failed", "feature_too_large"),
        ("done", None),
    ]


# -- 8. retry-failed never re-runs what the feature itself decided ----------------


async def test_base64_retry_settles_every_item_and_skips_parse_failures(imp):
    text = __import__("base64").b64encode(b"hello").decode()
    feats = [feature({"other": 1}), feature({"img": "!!"}), feature({"img": text})]
    job = await imp.job(feats)
    await imp.run(job)
    assert await imp.counts(job) == ("completed", 3, 3, 0, 0, 3)
    first = await imp.items(job)
    out = await controls.retry_failed(imp.runtime, T, job.id)
    assert out.status.value == "completed"  # it finishes; nothing is left pending
    again = await imp.items(job)
    assert [i.last_error for i in again] == ["missing_image", "invalid_base64", "unsupported_type"]
    assert again[0].updated_at == first[0].updated_at  # the parse failure was never reset
    assert await imp.counts(job) == ("completed", 3, 3, 0, 0, 3)


async def test_url_retry_does_not_download_a_feature_with_a_bad_external_id(imp, resolver, inner):
    seen = serve_images(resolver, inner, fail={"/x.jpg": httpx.Response(404)})
    feats = [
        feature({"url": f"https://{HOST}/bad-id.jpg", "id": "z" * 300}),
        feature({"url": f"https://{HOST}/x.jpg"}),
    ]
    job = await imp.job(feats, URL, url_prop="url", external_id_prop="id")
    await imp.run(job)
    seen.clear()
    await controls.retry_failed(imp.runtime, T, job.id)
    assert [r.url.path for r in seen] == ["/x.jpg"]
    assert [i.last_error for i in await imp.items(job)] == ["invalid_external_id", "http_404"]


# -- 9. a resumed run hands out its pending items itself (broker mode) -------------


async def test_resume_in_broker_mode_hands_out_pending_url_items(imp, monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", record)
    job = await imp.job([feature({"url": f"https://{HOST}/{i}.jpg"}) for i in range(3)], URL)
    await imp.run(job)
    first_ids = sent[0][1]
    await controls.pause(imp.runtime, T, job.id)
    runners: list[int] = []

    async def queued(runtime, tenant, job_id, generation):
        runners.append(generation)

    monkeypatch.setattr(launch, "launch_runner", queued)
    broker = dataclasses.replace(imp.runtime, eager=False)
    resumed = await controls.resume(broker, T, job.id)
    assert runners == [resumed.generation]
    sent.clear()
    assert await runner.import_geojson_async(broker, T, job.id, resumed.generation) == "running"
    assert sent == [(resumed.generation, first_ids)]


# -- 11. a base64 job with failures keeps its source until the grace period -------


async def test_a_base64_job_with_failures_keeps_its_source_until_the_grace_period(imp):
    from sm_images.janitor import janitor_async

    job = await imp.job([feature({"img": "!!"}), feature({"img": b64()})])
    await imp.run(job)
    kept = (await imp.reload(job)).source_key
    assert kept in imp.stored()
    out = await controls.retry_failed(imp.runtime, T, job.id)  # works while it is kept
    assert out.status.value == "completed"
    await janitor_async(imp.runtime, datetime.now(UTC) + timedelta(days=8))
    assert kept not in imp.stored() and (await imp.reload(job)).source_key is None
    with pytest.raises(Conflict) as err:
        await controls.retry_failed(imp.runtime, T, job.id)
    assert err.value.code == "source_gone"


async def test_a_base64_job_without_failures_deletes_its_source_at_once(imp):
    job = await imp.job([feature({"img": b64()})])
    await imp.run(job)
    assert (await imp.reload(job)).source_key is None
    assert not [k for k in imp.stored() if "/imports/" in k]


# -- 12. the long steps of a run heartbeat --------------------------------------


async def test_counting_and_storing_a_fetched_source_heartbeats(imp, resolver, inner, monkeypatch):
    monkeypatch.setattr(beat, "HEARTBEAT_SECONDS", 0.01)
    resolver["src.example"] = [PUBLIC_IP]
    serve_images(resolver, inner, fail={"/p.geojson": lambda r: body(geojson([]))})
    real_count, beats = staging.count, []

    async def slow_count(*a, **k):
        await asyncio.sleep(0.1)
        return await real_count(*a, **k)

    real_beat = jobs.heartbeat

    async def counting_beat(*a, **k):
        beats.append(1)
        return await real_beat(*a, **k)

    monkeypatch.setattr(staging, "count", slow_count)
    monkeypatch.setattr(jobs, "heartbeat", counting_beat)
    job = await jobs.create_job(
        imp.runtime,
        T,
        imp.coll.id,
        kind=URL,
        mapping=Mapping(url_prop="url"),
        source_url="https://src.example/p.geojson",
    )
    assert await imp.run(job) == "completed"
    assert len(beats) >= 2
