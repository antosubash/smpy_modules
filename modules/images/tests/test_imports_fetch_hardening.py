"""Resource bounds under hostile timing: DNS pool admission and cancelled TLS.

* A resolver thread that hangs keeps running after its lookup times out, so
  admission to the DNS pool is bounded: with every worker hung, the next lookup
  waits at most until its deadline and fails closed - nothing queues behind
  the hung threads.
* A fetch cancelled mid-handshake closes its socket (httpcore only closes on
  ``Exception``, which ``CancelledError`` is not).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import threading
import time

import pytest
from sm_images.imports import dns, url_safety
from sm_images.imports.fetch import FetchTimeoutError, safe_stream


async def _fetch(url: str, timeout: float, **kw) -> bytes:
    stream = safe_stream(url, max_bytes=1000, timeout=timeout, **kw)
    return b"".join([chunk async for chunk in stream])


@pytest.fixture
def hung_dns(monkeypatch):
    """Every lookup hangs until the test ends; afterwards the pool drains."""
    release = threading.Event()
    calls: list[str] = []

    def hang(host, *_a, **_k):
        calls.append(host)
        release.wait(10)
        raise OSError("released")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", hang)
    yield calls
    release.set()
    deadline = time.monotonic() + 5
    while dns.busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dns.busy() == 0


async def test_saturated_dns_pool_fails_closed_without_queueing(hung_dns, monkeypatch, caplog):
    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.05)
    for n in range(dns.POOL_SIZE):
        with pytest.raises(FetchTimeoutError):
            await _fetch(f"http://hung{n}.example/a.jpg", 5)
    assert dns.busy() == dns.POOL_SIZE  # timed out, but the threads still run

    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 30)
    started = time.monotonic()
    with (
        caplog.at_level(logging.WARNING, logger="sm_images.imports.dns"),
        pytest.raises(FetchTimeoutError),
    ):
        await _fetch("http://ninth.example/a.jpg", 0.2)
    assert time.monotonic() - started < 1
    assert dns._POOL._work_queue.qsize() == 0  # nothing queued behind the hung threads
    assert len(hung_dns) == dns.POOL_SIZE  # the ninth never reached getaddrinfo
    assert "saturated" in caplog.text


@pytest.fixture
async def stalling_server(resolver, monkeypatch):
    """Accepts TCP on 127.0.0.1 and never answers the TLS ClientHello; records
    when the client's side of each connection is closed (EOF)."""
    events = {"accepted": asyncio.Event(), "eof": asyncio.Event()}
    writers: list[asyncio.StreamWriter] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        events["accepted"].set()
        while await reader.read(4096):
            pass  # swallow the ClientHello, answer nothing
        events["eof"].set()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    resolver["stall.example"] = ["127.0.0.1"]
    loopback = ipaddress.ip_address("127.0.0.1")
    real_check = url_safety.is_public_address
    monkeypatch.setattr(
        url_safety, "is_public_address", lambda ip: ip == loopback or real_check(ip)
    )
    try:
        yield port, events
    finally:
        server.close()
        for writer in writers:  # a leaked client socket must not hang teardown
            writer.close()
        await asyncio.wait_for(server.wait_closed(), 2)


async def test_cancel_mid_handshake_closes_the_socket(stalling_server):
    port, events = stalling_server
    task = asyncio.create_task(
        _fetch(f"https://stall.example:{port}/a.jpg", 30, allowed_ports=frozenset({port}))
    )
    await asyncio.wait_for(events["accepted"].wait(), 2)
    await asyncio.sleep(0.05)  # the ClientHello is out; the handshake is waiting
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(events["eof"].wait(), 1)


async def test_deadline_mid_handshake_closes_the_socket(stalling_server):
    """Our own deadline (``asyncio.timeout_at``) is a cancellation too."""
    port, events = stalling_server
    with pytest.raises(FetchTimeoutError):
        await _fetch(f"https://stall.example:{port}/a.jpg", 0.2, allowed_ports=frozenset({port}))
    await asyncio.wait_for(events["eof"].wait(), 1)


def test_harden_installs_on_a_real_transport():
    """Guards the httpx internals ``harden`` relies on: an upgrade fails here loudly."""
    import httpx
    from sm_images.imports.netsafe import CancelSafeBackend, harden

    transport = harden(httpx.AsyncHTTPTransport())
    assert isinstance(transport._pool._network_backend, CancelSafeBackend)
    assert harden(transport) is transport  # idempotent
    assert not isinstance(harden(transport)._pool._network_backend._backend, CancelSafeBackend)
