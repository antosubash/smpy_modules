"""A URL item is claimed when it gets its limiter slot, just before its fetch -
not up front for the whole batch. Claimed up front, an item queued behind the
per-domain limit could outwait its claim; reconcile's re-send then claimed it
too, and both runs fetched it."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest
from sm_images.clock import utcnow
from sm_images.imports import download, item_claim, launch, retrying
from sm_images.tenancy import DEFAULT_TENANT as T

from tests.support.imports import HOST, URL, feature, serve_images

FETCH = 0.4
"""How far one fetch moves the claims' clock (claim-clock seconds)."""
TTL = 1.0
"""The claim's lifetime: longer than one fetch, shorter than four in a row."""


@pytest.fixture
def broker(monkeypatch):
    sent: list[tuple[int, list[int]]] = []

    async def fake(runtime, tenant, job_id, generation, ids):
        sent.append((generation, list(ids)))

    monkeypatch.setattr(launch, "launch_downloads", fake)
    return sent


class ClaimClock:
    """The clock claims are stamped and judged by; it moves only when a fetch
    says so, so no claim expires early because the machine is slow."""

    def __init__(self) -> None:
        self.start = utcnow()
        self.elapsed = 0.0

    def __call__(self):
        return self.start + timedelta(seconds=self.elapsed)


async def test_a_queued_item_is_not_fetched_twice_when_its_run_is_resent(
    imp, resolver, inner, broker, monkeypatch
):
    serve_images(resolver, inner)
    urls = [f"https://{HOST}/{n}.jpg" for n in range(4)]
    job = await imp.job([feature({"url": u}) for u in urls], URL)
    assert await imp.run(job) == "running"
    clock = ClaimClock()
    monkeypatch.setattr(item_claim, "now", clock)
    monkeypatch.setattr(item_claim, "CLAIM_SECONDS", TTL)
    imp.pipe.settings.download_concurrency_per_domain = 1  # one host: they queue
    generation, ids = broker[0]
    fetched: Counter[str] = Counter()
    resent: list[int] = []
    sent_again: list[bool] = []
    real = retrying.safe_stream

    async def fetch(url, **kw):
        fetched[str(url)] += 1
        clock.elapsed += FETCH  # each fetch holds its slot for FETCH
        if str(url) == urls[2] and not sent_again:
            sent_again.append(True)
            # The third fetch is in flight and the queue has outwaited one TTL
            # (item 0 was the first in line at 0 s): reconcile re-sends the batch.
            assert clock.elapsed > TTL
            resent.append(
                await download.download_items_async(imp.runtime, T, job.id, generation, ids)
            )
        async for chunk in real(url, **kw):
            yield chunk

    monkeypatch.setattr(retrying, "safe_stream", fetch)
    first = await download.download_items_async(imp.runtime, T, job.id, generation, ids)
    assert resent == [1], "the resent run should hold only the item still queued"
    assert first + resent[0] == len(urls)  # every item held by exactly one run
    assert fetched == Counter(dict.fromkeys(urls, 1))
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
