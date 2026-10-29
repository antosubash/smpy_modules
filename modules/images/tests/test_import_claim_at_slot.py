"""A URL item is claimed when it gets its limiter slot, just before its fetch -
not up front for the whole batch. Claimed up front, an item queued behind the
per-domain limit could outwait its claim; reconcile's re-send then claimed it
too, and both runs fetched it."""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest
from sm_images.imports import download, item_claim, launch, retrying
from sm_images.tenancy import DEFAULT_TENANT as T

from tests.import_support import HOST, URL, feature, serve_images

FETCH = 0.4
"""How long one fetch holds its slot."""
TTL = 1.0
"""The claim's lifetime: shorter than four fetches in a row."""


@pytest.fixture
def broker(monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", fake)
    return sent


@pytest.fixture
def slow_fetches(monkeypatch) -> Counter[str]:
    fetched: Counter[str] = Counter()
    real = retrying.safe_stream

    async def slow(url, **kw):
        fetched[str(url)] += 1
        await asyncio.sleep(FETCH)
        async for chunk in real(url, **kw):
            yield chunk

    monkeypatch.setattr(retrying, "safe_stream", slow)
    return fetched


async def test_a_queued_item_is_not_fetched_twice_when_its_run_is_resent(
    imp, resolver, inner, broker, slow_fetches, monkeypatch
):
    serve_images(resolver, inner)
    urls = [f"https://{HOST}/{n}.jpg" for n in range(4)]
    job = await imp.job([feature({"url": u}) for u in urls], URL)
    assert await imp.run(job) == "running"
    monkeypatch.setattr(item_claim, "CLAIM_SECONDS", TTL)
    imp.pipe.settings.download_concurrency_per_domain = 1  # one host: they queue
    generation, ids = broker[0]

    async def resent_after_the_ttl():
        await asyncio.sleep(TTL + 0.05)  # reconcile re-sends the batch
        return await download.download_items_async(imp.runtime, T, job.id, generation, ids)

    first = download.download_items_async(imp.runtime, T, job.id, generation, ids)
    held = await asyncio.gather(first, resent_after_the_ttl())
    assert sum(held) == len(urls)  # every item held by exactly one run
    assert slow_fetches == Counter(dict.fromkeys(urls, 1))
    assert await imp.statuses(job) == ["done"] * len(urls)


async def test_an_item_never_claimed_is_left_for_reconcile(imp, resolver, inner, broker):
    """A run whose generation moved claims nothing: its items stay pending,
    unclaimed, and nothing is fetched."""
    seen = serve_images(resolver, inner)
    job = await imp.job([feature({"url": f"https://{HOST}/a.jpg"})], URL)
    assert await imp.run(job) == "running"
    generation, ids = broker[0]
    held = await download.download_items_async(imp.runtime, T, job.id, generation + 1, ids)
    assert held == 0 and seen == []
    (item,) = await imp.items(job)
    assert (item.status.value, item.claim_token) == ("pending", None)
