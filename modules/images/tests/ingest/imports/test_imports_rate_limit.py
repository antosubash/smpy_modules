"""``sm_images.ingest.imports.rate_limit``: ``DomainLimiter`` and ``backoff``."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from sm_images.ingest.imports import rate_limit
from sm_images.ingest.imports.rate_limit import (
    MAX_BACKOFF_SECONDS,
    DomainLimiter,
    backoff,
    domain_of,
)


async def _run(limiter: DomainLimiter, urls: list[str]) -> dict[str, int]:
    """Hold a slot per URL briefly; report the peak concurrency per domain and overall."""
    active: dict[str, int] = {}
    peak: dict[str, int] = {}

    async def one(url: str) -> None:
        domain = domain_of(url)
        async with limiter.slot(url):
            active[domain] = active.get(domain, 0) + 1
            active["*"] = active.get("*", 0) + 1
            peak[domain] = max(peak.get(domain, 0), active[domain])
            peak["*"] = max(peak.get("*", 0), active["*"])
            await asyncio.sleep(0.01)
            active[domain] -= 1
            active["*"] -= 1

    await asyncio.gather(*(one(u) for u in urls))
    return peak


async def test_per_domain_concurrency():
    limiter = DomainLimiter(per_domain=2, total=10)
    urls = [f"https://a.example/{i}" for i in range(8)] + [
        f"https://b.example/{i}" for i in range(8)
    ]
    peak = await _run(limiter, urls)
    assert peak["a.example"] == 2
    assert peak["b.example"] == 2
    assert peak["*"] == 4


async def test_total_caps_all_domains():
    limiter = DomainLimiter(per_domain=5, total=3)
    peak = await _run(limiter, [f"https://d{i}.example/x" for i in range(9)])
    assert peak["*"] == 3


async def test_a_busy_domain_does_not_starve_others():
    """A waiter for a full domain holds no global slot while it waits."""
    limiter = DomainLimiter(per_domain=1, total=2)
    order: list[str] = []
    release = asyncio.Event()

    async def hold(url: str) -> None:
        async with limiter.slot(url):
            order.append(url)
            await release.wait()

    tasks = [asyncio.create_task(hold(f"https://a.example/{i}")) for i in range(3)]
    await asyncio.sleep(0.01)
    other = asyncio.create_task(hold("https://b.example/1"))
    await asyncio.sleep(0.01)
    assert order == ["https://a.example/0", "https://b.example/1"]
    release.set()
    await asyncio.gather(*tasks, other)


async def test_slot_is_released_on_error_and_state_is_pruned():
    limiter = DomainLimiter(per_domain=1, total=1)
    with pytest.raises(RuntimeError):
        async with limiter.slot("https://a.example/x"):
            raise RuntimeError("boom")
    async with asyncio.timeout(1):
        async with limiter.slot("https://a.example/y"):
            pass
    assert limiter.tracked_domains() == 0


def test_domain_key_is_the_lowercased_host():
    assert domain_of("https://IMG.Example.org:443/a.jpg") == "img.example.org"
    assert domain_of("not a url") == "unknown"


def test_limits_must_be_positive():
    with pytest.raises(ValueError):
        DomainLimiter(per_domain=0, total=1)
    with pytest.raises(ValueError):
        DomainLimiter(per_domain=1, total=0)


def _response(status: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(status, headers=headers)


@pytest.mark.parametrize("attempt", [0, 3])
def test_retry_after_honoured(attempt):
    """Never retried before the server said; jitter only ever adds."""
    for _ in range(50):
        delay = backoff(_response(429, "10"), attempt)
        assert 10 <= delay <= 10 * 1.25


def test_retry_after_http_date_is_honoured(monkeypatch):
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(rate_limit, "_utcnow", lambda: now)
    header = format_datetime(now + timedelta(seconds=42), usegmt=True)
    assert 42 <= backoff(_response(503, header), 0) <= 42 * 1.25


def test_retry_after_in_the_past_retries_soon(monkeypatch):
    now = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(rate_limit, "_utcnow", lambda: now)
    header = format_datetime(now - timedelta(seconds=42), usegmt=True)
    assert 0 <= backoff(_response(503, header), 0) <= 2


def test_retry_after_beyond_the_cap_gives_up_instead_of_retrying_early():
    """A server asking for 10 minutes is not hit again after 5: the caller defers."""
    assert backoff(_response(429, str(MAX_BACKOFF_SECONDS + 1)), 0) is None
    assert backoff(_response(429, str(MAX_BACKOFF_SECONDS)), 0) == pytest.approx(
        MAX_BACKOFF_SECONDS
    )


@pytest.mark.parametrize("header", [None, "", "soon", "-5", "1e3"])
def test_unparsable_retry_after_falls_back_to_exponential(header):
    first = backoff(_response(503, header), 0)
    later = backoff(_response(503, header), 4)
    assert 0 < first <= 1.25
    assert 16 <= later <= 16 * 1.25


def test_exponential_backoff_is_capped():
    assert backoff(None, 30) <= MAX_BACKOFF_SECONDS
    assert MAX_BACKOFF_SECONDS == 300


@pytest.mark.parametrize(
    ("status", "retry"),
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (408, True),
        (400, False),
        (403, False),
        (404, False),
        (410, False),
    ],
)
def test_retryable_statuses(status, retry):
    assert rate_limit.is_retryable_status(status) is retry


@pytest.mark.parametrize(
    "url",
    [
        "https://xn--bcher-kva.example/a",
        "https://BÜCHER.example./a",
        "https://bücher.example:443/b",
        "http://XN--BCHER-KVA.EXAMPLE./c",
    ],
)
def test_domain_keys_are_normalised(url):
    """Case, IDNA form and a trailing dot name one host, so they share one limit."""
    assert domain_of(url) == "xn--bcher-kva.example"
