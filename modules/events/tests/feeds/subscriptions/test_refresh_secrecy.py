"""Through the whole pass (the beat's own path), no log record at any level carries the address."""

from __future__ import annotations

import asyncio
import logging
import ssl

import httpx
import pytest
from sm_events.feeds.subscriptions import fetch

from tests.feeds.subscriptions.refresh_support import load, seed, tick
from tests.support.net import PUBLIC_IP, ics, inner, resolver  # noqa: F401

pytestmark = pytest.mark.unbound_tenant
SECRET = "https://cal.example/private-TOKEN7777/basic.ics?key=TOKEN7777"


def _tls(request):
    try:
        raise ssl.SSLCertVerificationError(f"certificate verify failed for {request.url}")
    except ssl.SSLError as cause:
        raise httpx.ConnectError(f"tls {request.url}") from cause


async def _slow(request):
    await asyncio.sleep(30)


def _handler(case):
    def handler(request):
        if case == "connect":
            raise httpx.ConnectError(f"cannot connect to {request.url}")
        if case == "tls":
            return _tls(request)
        if case == "timeout":
            raise httpx.ReadTimeout(f"timed out {request.url}")
        if case == "redirect":
            return httpx.Response(302, headers={"location": "https://internal.example/x?TOKEN7777"})
        if case == "big":
            return httpx.Response(200, content=b"X" * 5_000_000 + SECRET.encode())
        if case == "unexpected":
            raise RuntimeError(f"surprise {request.url}")
        return ics()

    return handler


@pytest.mark.parametrize(
    "case", ["connect", "tls", "timeout", "redirect", "big", "unexpected", "ok"]
)
async def test_no_log_record_carries_the_address(db_state, inner, resolver, caplog, case):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.9"]
    inner(_handler(case))
    (sid,) = await seed(db_state, url=SECRET)
    with caplog.at_level(logging.DEBUG):
        await tick(db_state, fetch.fetch_feed)
    sub = await load(db_state, sid)
    assert sub.error_code in {
        None,
        "connect_failed",
        "tls_failed",
        "timeout",
        "url_unreachable",
        "too_large",
        "internal",
    }
    assert "TOKEN7777" not in repr(sub.__dict__) and "TOKEN7777" not in sub.url_display
    for record in caplog.records:
        blob = record.getMessage() + repr(record.__dict__) + (record.exc_text or "")
        assert "TOKEN7777" not in blob, (case, record.name)
