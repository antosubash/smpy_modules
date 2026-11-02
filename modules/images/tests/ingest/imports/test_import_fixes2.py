"""Review round 2: fenced claim release, generation-scoped clean-up, byte budget."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.ingest.imports import chunk, controls, download, jobs, launch, runner, terminal
from sm_images.ingest.imports.geojson_stream import OVERSIZE, iter_features
from sm_images.models import ImportItem
from sqlalchemy import select

from tests.support.imports import HOST, URL, b64, feature, geojson

T = DEFAULT_TENANT


async def _claims(imp) -> list[str | None]:
    async with imp.pipe.db_state.session_factory() as s:
        return list((await s.execute(select(ImportItem.claim_token))).scalars())


# -- 1. a delayed old runner cannot clear the current generation's claims ---------


async def test_an_old_runner_does_not_clear_the_new_generations_claims(imp, monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", record)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    old = jobs.snapshot(await imp.reload(job))  # the old runner, delayed after its start
    item_id = sent[0][1][0]
    await controls.pause(imp.runtime, T, job.id)
    resumed = await controls.resume(imp.runtime, T, job.id, launch=False)
    assert await imp.run(job, resumed.generation) == "running"
    held = await download._claim(imp.runtime, T, job.id, resumed.generation, item_id)
    assert held is not None
    with pytest.raises(chunk.Stopped):  # the old run stops without touching anything
        await runner._hand_out_pending(imp.runtime, T, old, old.total_count)
    assert await _claims(imp) == [held[1]]
    # The current run handing out again releases only claims older than its own.
    current = jobs.snapshot(await imp.reload(job))
    await runner._hand_out_pending(imp.runtime, T, current, current.total_count)
    assert await _claims(imp) == [held[1]]


async def test_a_new_run_releases_claims_of_an_older_generation(imp, monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def record(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", record)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    await imp.run(job)
    item_id = sent[0][1][0]
    assert await download._claim(imp.runtime, T, job.id, job.generation, item_id) is not None
    await controls.pause(imp.runtime, T, job.id)
    resumed = await controls.resume(imp.runtime, T, job.id, launch=False)
    sent.clear()
    await imp.run(job, resumed.generation)
    assert await _claims(imp) == [None]
    assert sent == [(resumed.generation, [item_id])]


# -- 2. clean-up acts only for the generation that triggered it ------------------


async def test_a_stale_cleanup_cannot_delete_a_newer_generations_retained_source(imp):
    job = await imp.job([feature({"img": "!!"}), feature({"img": b64()})])
    await imp.run(job)
    first = await imp.reload(job)
    kept = first.source_key
    retried = await controls.retry_failed(
        imp.runtime, T, job.id
    )  # a new generation, failures again
    assert retried.generation > first.generation and retried.status.value == "completed"
    # The first completion's clean-up arrives late - even as the janitor's
    # past-grace sweep, it does not act for a generation that moved on ...
    assert await terminal.release_staging(imp.runtime, T, job.id, first.generation) is False
    future = datetime.now(UTC) + timedelta(days=30)
    late = await terminal.release_staging(
        imp.runtime, T, job.id, first.generation, grace_cutoff=future
    )
    assert late is False
    # ... and the current generation's own is not eligible either: it has failures.
    assert await terminal.release_staging(imp.runtime, T, job.id, retried.generation) is False
    assert (await imp.reload(job)).source_key == kept and kept in imp.stored()


# -- 3. the feature budget counts UTF-8 bytes and covers bare scalars ------------


def test_the_budget_counts_utf8_bytes_not_characters():
    doc = geojson([{"p": "é" * 60}, {"p": "e" * 60}])
    got = list(iter_features(io.BytesIO(doc), 0, max_feature_bytes=100))
    assert got == [(0, OVERSIZE), (1, {"p": "e" * 60})]


def test_a_bare_scalar_feature_over_the_budget_is_too_large():
    doc = geojson(["x" * 200, "ok", 3])
    got = list(iter_features(io.BytesIO(doc), 0, max_feature_bytes=100))
    assert got == [(0, OVERSIZE), (1, "ok"), (2, 3)]


async def test_a_bare_scalar_too_large_fails_its_item(imp):
    imp.pipe.settings.geojson_max_feature_bytes = 4000
    job = await imp.job(["x" * 5000, feature({"img": b64()})])
    assert await imp.run(job) == "completed"
    assert [i.last_error for i in await imp.items(job)] == ["feature_too_large", None]
