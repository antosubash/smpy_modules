"""The bounded resolver pool: admission is bounded, so a hung resolver cannot pile up threads
or hold a fetch past its deadline."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx
import pytest
from sm_events.feeds.subscriptions import dns, policy
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import fake_dns

OFF = policy.Policy(allow_private=False)


def _url(host: str) -> httpx.URL:
    return httpx.URL(f"https://{host}/a.ics")


@pytest.fixture
def hung_dns(monkeypatch):
    """Every lookup hangs until the test ends; afterwards the pool drains."""
    release = threading.Event()
    calls: list[str] = []

    def hang(host, *_a, **_k):
        calls.append(host)
        release.wait(10)
        raise OSError("released")

    fake_dns(monkeypatch, hang)
    yield calls
    release.set()
    deadline = time.monotonic() + 5
    while dns.busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dns.busy() == 0


async def test_a_hung_lookup_times_out_closed(hung_dns, monkeypatch):
    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.05)
    with pytest.raises(FetchFailure) as caught:
        await dns.resolve_bounded(_url("hung.example"), OFF)
    assert caught.value.code == "timeout"
    assert str(caught.value) == "timeout"


async def test_saturated_dns_pool_fails_closed_without_queueing(hung_dns, monkeypatch, caplog):
    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.05)
    for n in range(dns.POOL_SIZE):
        with pytest.raises(FetchFailure):
            await dns.resolve_bounded(_url(f"hung{n}.example"), OFF)
    assert dns.busy() == dns.POOL_SIZE  # timed out, but the threads still run

    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.3)
    started = time.monotonic()
    with (
        caplog.at_level(logging.WARNING, logger="sm_events.feeds.subscriptions.dns"),
        pytest.raises(FetchFailure),
    ):
        await dns.resolve_bounded(_url("next.example"), OFF)
    assert time.monotonic() - started < 1.5
    assert dns._POOL._work_queue.qsize() == 0  # nothing queued behind the hung threads
    assert len(hung_dns) == dns.POOL_SIZE  # the next one never reached getaddrinfo
    assert "saturated" in caplog.text


@pytest.fixture
def no_polling(monkeypatch):
    calls: list[float] = []
    real_sleep = asyncio.sleep

    async def sleep(delay, *args, **kwargs):
        calls.append(delay)
        return await real_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(dns.asyncio, "sleep", sleep)
    return calls


async def test_a_waiter_is_woken_by_a_release_from_a_worker_thread(hung_dns, no_polling):
    for _ in range(dns.POOL_SIZE):
        assert dns._try_admit()
    try:
        waiter = asyncio.ensure_future(dns._admit())
        done, _ = await asyncio.wait({waiter}, timeout=0.05)
        assert not done  # parked: every slot is held
        threading.Thread(target=dns._release).start()
        await asyncio.wait_for(waiter, 1)
        assert dns.busy() == dns.POOL_SIZE
        assert no_polling == []
    finally:
        for _ in range(dns.busy()):
            dns._release()


async def test_saturated_admission_times_out_without_polling(hung_dns, no_polling, monkeypatch):
    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.2)
    for _ in range(dns.POOL_SIZE):
        assert dns._try_admit()
    try:
        with pytest.raises(FetchFailure):
            await dns.resolve_bounded(_url("tenth.example"), OFF)
        assert no_polling == []
        assert dns.busy() == dns.POOL_SIZE  # a timed-out waiter takes no slot
    finally:
        for _ in range(dns.busy()):
            dns._release()


def test_the_pool_is_events_own():
    assert dns.POOL_SIZE == 4
    assert dns._POOL._thread_name_prefix == "sm-events-dns"
