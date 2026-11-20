"""``fetch_feed`` end to end over the loopback TLS server (fixtures: ``conftest.py``)."""

from __future__ import annotations

import asyncio

import pytest
from sm_events.feeds.subscriptions import fetch, policy
from sm_events.feeds.subscriptions.errors import FetchFailure

from tests.feeds.subscriptions.conftest import ICS

ON = policy.Policy(allow_private=True, may_use_private=True)


async def _fetch(url: str, timeout: float = 5):
    return await fetch.fetch_feed(
        url, policy=ON, etag=None, last_modified=None, max_bytes=10_000, timeout=timeout
    )


async def test_a_real_fetch_returns_the_body(tls_server):
    port, seen = tls_server
    result = await _fetch(f"https://cal.example:{port}/feed.ics")
    assert (result.status, result.body, result.http_status) == ("ok", ICS, 200)
    assert seen["sni"] == "cal.example"
    assert seen["host"] == f"cal.example:{port}"


async def test_the_wrong_name_is_a_tls_failure(tls_server):
    port, _ = tls_server
    with pytest.raises(FetchFailure) as caught:
        await _fetch(f"https://wrong.example:{port}/feed.ics")
    assert caught.value.code == "tls_failed"


async def test_loopback_is_refused_with_the_one_unreachable_answer(tls_server, monkeypatch):
    port, seen = tls_server
    monkeypatch.setattr(policy, "address_allowed", seen["real"])
    with pytest.raises(FetchFailure) as caught:
        await _fetch(f"https://cal.example:{port}/feed.ics")
    assert caught.value.code == "url_unreachable"
    assert "sni" not in seen


async def test_a_stalled_handshake_ends_at_the_deadline_and_closes_the_socket(stalling_server):
    port, events = stalling_server
    with pytest.raises(FetchFailure) as caught:
        await _fetch(f"https://stall.example:{port}/a.ics", timeout=0.3)
    assert caught.value.code == "timeout"
    await asyncio.wait_for(events["eof"].wait(), 1)


async def test_no_token_reaches_a_log_record_even_at_debug_through_the_real_stack(
    tls_server, caplog
):
    """httpcore logs its connection steps at DEBUG: none of them carries the path."""
    import logging

    port, _ = tls_server
    with caplog.at_level(logging.DEBUG):
        await _fetch(f"https://cal.example:{port}/private-TOKEN9999/basic.ics")
    for record in caplog.records:
        blob = record.getMessage() + repr(record.__dict__)
        assert "TOKEN9999" not in blob
    assert any(r.name.startswith("httpcore") for r in caplog.records)  # the test saw them
