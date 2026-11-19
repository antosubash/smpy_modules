"""No log line, whatever logged it, carries a feed token or its digest."""

from __future__ import annotations

import logging

from simple_module_hosting._observability import RequestLoggingMiddleware
from simple_module_hosting._rate_limit import RateLimitMiddleware
from sm_events.core import constants
from sm_events.feeds.tokens import log_redact
from sm_events.feeds.tokens.codec import hash_token
from sm_events.web.endpoints.public import _private_feed

from tests.support.private_feed import feed_path, invented, private_http, seed_world


def assert_clean(caplog, *secrets: str) -> None:
    server = [r for r in caplog.records if not r.name.startswith("http")]  # not the test client's
    assert server, "nothing was logged: the test proves nothing"
    needles = [*secrets, *(hash_token(s) for s in secrets)]
    for record in server:
        text = record.getMessage() + " " + str(record.__dict__)
        for needle in needles:
            assert needle not in text, (record.name, record.getMessage())


async def test_no_token_in_any_log_record(monkeypatch, caplog):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    log_redact.install()
    async with private_http() as http:
        world = await seed_world(http)
        http.app.add_middleware(RateLimitMiddleware, public_rate=None)
        http.app.add_middleware(RequestLoggingMiddleware)
        denied = invented("K")
        with caplog.at_level(logging.DEBUG):
            assert (await http.get(world.path)).status_code == 200  # a success
            assert (await http.get(feed_path(denied))).status_code == 404  # a deny

            async def boom(*_a, **_k):
                raise RuntimeError(f"failed for {feed_path(world.secret)}")

            with monkeypatch.context() as patch:
                patch.setattr(_private_feed, "resolve", boom)
                assert (await http.get(world.path)).status_code == 404  # a failing check
            with monkeypatch.context() as patch:
                patch.setattr(_private_feed, "lookup", boom)
                assert (await http.get(world.path)).status_code == 503  # a forced failure

            for _ in range(constants.FEED_TOKEN_RATE):  # until the per-token window says 429
                await http.get(feed_path(denied))
            assert (await http.get(feed_path(denied))).status_code == 429

            for i in range(30):  # the per-IP limit: the request guard logs its 429
                await http.get(feed_path(f"evf_{i:043d}"))
            assert (await http.get(feed_path(f"evf_{99:043d}"))).status_code == 429
        assert_clean(caplog, world.secret, denied)
        # The request log did see these requests, with the path redacted.
        paths = [getattr(r, "path", "") for r in caplog.records if hasattr(r, "path")]
        assert any(p.endswith("/feed/<redacted>") for p in paths), paths


async def test_the_filter_is_what_protects_the_log(monkeypatch, caplog):
    """Without the filter the request log does carry the path: the test above is not vacuous."""
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    for name in log_redact.LOGGERS:
        target = logging.getLogger(name)
        target.filters = [f for f in target.filters if not isinstance(f, log_redact.Filter)]
    for handler in log_redact._handlers():  # handlers carry the filter too since install()
        handler.filters = [f for f in handler.filters if not isinstance(f, log_redact.Filter)]
    async with private_http() as http:
        world = await seed_world(http)
        http.app.add_middleware(RequestLoggingMiddleware)
        with caplog.at_level(logging.DEBUG):
            await http.get(world.path)
    leaked = any(world.secret in str(r.__dict__) for r in caplog.records)
    assert leaked
    log_redact.install()
