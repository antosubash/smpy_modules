"""A private feed's failures and bookkeeping: outages, ``last_used_at``, the per-token window."""

from __future__ import annotations

from sm_events.core import constants
from sm_events.feeds.tokens import resolve as resolve_module
from sm_events.feeds.tokens import service
from sm_events.models import FeedToken
from sm_events.web.endpoints.public import _private_feed
from sqlalchemy import select

from tests.support.private_feed import feed_path, invented, private_http, seed_world
from tests.support.tokens import NOW


async def test_internal_error_is_503_without_token(monkeypatch, caplog):
    """The database itself failing (before any row is known) is the one other shape: a fixed
    503 that names nothing about the token."""
    async with private_http() as http:
        world = await seed_world(http)

        async def boom(*_a, **_k):
            raise RuntimeError(f"database down for {world.path}")

        monkeypatch.setattr(_private_feed, "lookup", boom)
        with caplog.at_level("DEBUG"):
            got = await http.get(world.path)
            unknown = await http.get(feed_path(invented()))
        for answer in (got, unknown):  # a valid and an invented token fail the same way
            assert answer.status_code == 503
            assert answer.headers["cache-control"] == "no-store"
            assert answer.json() == {"detail": "Service unavailable", "code": "service_unavailable"}
        server = [r for r in caplog.records if not r.name.startswith("http")]  # not the client's
        assert server and all(world.secret not in r.getMessage() for r in server)
        assert world.secret not in got.text
        assert "RuntimeError" in caplog.text


async def test_a_failing_check_after_the_row_is_found_is_the_refusal(monkeypatch, caplog):
    """A dependency raising for a link that exists answers as an unknown link does: padded,
    the same bytes, so the outage is no oracle. The class is logged, never the token."""
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)

        async def boom(*_a, **_k):
            raise RuntimeError(f"directory down for {world.path}")

        monkeypatch.setattr(_private_feed, "resolve", boom)
        with caplog.at_level("DEBUG"):
            valid = await http.get(world.path)
            unknown = await http.get(feed_path(invented()))
        assert (valid.status_code, valid.content) == (404, constants.PRIVATE_FEED_ERROR_BODY)
        assert valid.content == unknown.content
        assert {k: v for k, v in valid.headers.items() if k != "date"} == {
            k: v for k, v in unknown.headers.items() if k != "date"
        }
        server = [r for r in caplog.records if not r.name.startswith("http")]
        assert any("RuntimeError" in r.getMessage() for r in server)
        assert all(world.secret not in r.getMessage() for r in server)


async def _last_used(http, token_id):
    async with http.db_state.session_factory() as db:
        return (
            await db.execute(select(FeedToken.last_used_at).where(FeedToken.id == token_id))
        ).scalar_one()


async def test_last_used_touched_after_success_only(monkeypatch):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        assert await _last_used(http, world.token_id) is None
        assert (await http.get(feed_path(invented()))).status_code == 404
        assert await _last_used(http, world.token_id) is None
        assert (await http.get(world.path)).status_code == 200
        assert await _last_used(http, world.token_id) is not None

        # A revoked link is a refusal, and a refusal records nothing.
        async with http.db_state.session_factory() as db:
            from sm_events.core.tenancy import tenant_scope

            with tenant_scope("default"):
                from tests.support.access import principal

                await service.revoke_token(
                    db, principal("sv", "events.view"), world.token_id, now=NOW
                )
                row = (await db.execute(select(FeedToken))).scalar_one()
                row.last_used_at = None
                await db.commit()
        assert (await http.get(world.path)).status_code == 404
        assert await _last_used(http, world.token_id) is None


async def test_a_failing_touch_still_serves(monkeypatch):
    async with private_http() as http:
        world = await seed_world(http)

        async def broken(*_a, **_k):
            raise ConnectionError("db down")

        monkeypatch.setattr(resolve_module, "finalize_session", broken)
        assert (await http.get(world.path)).status_code == 200


async def test_junk_tokens_cannot_free_a_real_links_throttle(monkeypatch):
    from sm_events.feeds.tokens.throttle import TokenThrottle

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    small = TokenThrottle(limit=2, window=600, max_keys=3)
    monkeypatch.setattr(_private_feed, "THROTTLE", small)
    async with private_http() as http:
        world = await seed_world(http)
        assert [(await http.get(world.path)).status_code for _ in range(2)] == [200, 200]
        for i in range(20):  # junk far beyond the pool
            assert (await http.get(feed_path(f"evf_{i:043d}"))).status_code == 404
        assert (await http.get(world.path)).status_code == 429


async def _revoke(http, world):
    async with http.db_state.session_factory() as db:
        from sm_events.core.tenancy import tenant_scope

        from tests.support.access import principal

        with tenant_scope("default"):
            await service.revoke_token(db, principal("sv", "events.view"), world.token_id, now=NOW)
            await db.commit()


def _comparable(answer):
    return (
        answer.status_code,
        answer.content,
        {k: v for k, v in answer.headers.items() if k not in ("date", "retry-after")},
    )


async def test_a_revoked_token_is_throttled_exactly_like_an_invented_one(monkeypatch):
    """Row exists but refused vs no such row: the same budget, and at the limit the same 429."""
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        await _revoke(http, world)
        junk = feed_path(invented())
        limit = constants.FEED_TOKEN_RATE
        revoked = [await http.get(world.path) for _ in range(limit + 1)]
        unknown = [await http.get(junk) for _ in range(limit + 1)]
        assert [r.status_code for r in revoked] == [404] * limit + [429]
        assert [r.status_code for r in unknown] == [404] * limit + [429]
        assert [_comparable(r) for r in revoked] == [_comparable(r) for r in unknown]
        assert revoked[-1].headers["retry-after"] == unknown[-1].headers["retry-after"]


async def test_a_refused_row_is_evicted_by_junk_like_an_invented_token(monkeypatch):
    """Only a *served* link earns the pool junk cannot evict from; a refused one is junk too, so a
    flood frees both alike (no request sequence tells a refused row from no row)."""
    from sm_events.feeds.tokens.throttle import TokenThrottle

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    small = TokenThrottle(limit=2, window=600, max_keys=3)
    monkeypatch.setattr(_private_feed, "THROTTLE", small)
    async with private_http() as http:
        world = await seed_world(http)
        await _revoke(http, world)
        mine = feed_path(invented())
        for path in (world.path, mine):
            assert [(await http.get(path)).status_code for _ in range(2)] == [404, 404]
            assert (await http.get(path)).status_code == 429
        for i in range(20):  # junk far beyond the pool
            await http.get(feed_path(f"evf_{i:043d}"))
        assert (await http.get(world.path)).status_code == 404
        assert (await http.get(mine)).status_code == 404
