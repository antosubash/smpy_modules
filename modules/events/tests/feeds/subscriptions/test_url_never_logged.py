"""A subscription URL's secret never reaches a log record or an exception text, at any level, on
any logger (httpx's, httpcore's, asyncio's, ours): real sockets for connect, TLS and timeout
failures, a faked connection layer for a refused redirect and an oversized body."""

from __future__ import annotations

import logging
import socket
import traceback

import httpx
import pytest
from sm_events.feeds.subscriptions import fetch, policy
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.support.net import PUBLIC_IP, inner, resolver  # noqa: F401

ON = policy.Policy(allow_private=True, may_use_private=True)
PATH = "/private/SECRET-TOKEN-123/basic.ics?key=SECRET2"
SECRETS = ("SECRET-TOKEN-123", "SECRET2", "private/SECRET")


def _clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, secret


async def _run(
    host: str, port: int | None, caplog, timeout: float = 5.0, pol: policy.Policy = ON
) -> FetchFailure:
    url = f"https://{host}{'' if port is None else f':{port}'}{PATH}"
    with caplog.at_level(logging.DEBUG), pytest.raises(FetchFailure) as caught:
        await fetch.fetch_feed(
            url, policy=pol, etag=None, last_modified=None, max_bytes=100_000, timeout=timeout
        )
    failure = caught.value
    _clean(str(failure) + repr(failure) + repr(failure.args))
    _clean("".join(traceback.format_exception(failure)))
    for record in caplog.records:
        _clean(record.getMessage() + repr(record.__dict__) + (record.exc_text or ""))
    return failure


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_connect_error(tls_server, caplog):
    failure = await _run("cal.example", _closed_port(), caplog)
    assert failure.code == "connect_failed"


async def test_tls_error(tls_server, caplog):
    port, _ = tls_server
    assert (await _run("wrong.example", port, caplog)).code == "tls_failed"


async def test_timeout(stalling_server, caplog):
    port, _ = stalling_server
    assert (await _run("stall.example", port, caplog, timeout=0.3)).code == "timeout"


async def test_redirect_refusal(inner, resolver, caplog):  # noqa: F811
    resolver["feeds.example.test"] = [PUBLIC_IP]
    resolver["internal.example"] = ["10.0.0.9"]
    inner(lambda r: httpx.Response(302, headers={"location": f"https://internal.example{PATH}"}))
    failure = await _run("feeds.example.test", None, caplog, pol=policy.Policy())
    assert failure.code == "url_unreachable"


async def test_oversize_body(inner, resolver, caplog):  # noqa: F811
    resolver["feeds.example.test"] = [PUBLIC_IP]
    inner(lambda r: httpx.Response(200, content=b"X" * 300_000))
    assert (await _run("feeds.example.test", None, caplog)).code == "too_large"


async def test_a_refused_address_logs_neither_the_name_nor_the_address(monkeypatch, caplog):
    from sm_events.feeds.subscriptions import url_safety

    def private(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.8.7", port))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", private)
    with caplog.at_level(logging.DEBUG), pytest.raises(url_safety.UnsafeURLError):
        policy.resolve_allowed(
            httpx.URL("https://token-in-subdomain-77.example/x.ics"), policy.Policy()
        )
    assert caplog.records, "the refusal is still logged"
    for record in caplog.records:
        text = record.getMessage() + repr(record.__dict__)
        assert "token-in-subdomain-77" not in text and "10.9.8.7" not in text
