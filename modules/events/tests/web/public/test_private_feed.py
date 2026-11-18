"""A private feed link: what it serves, how it is cached, and how it is limited."""

from __future__ import annotations

import icalendar
from simple_module_hosting._rate_limit import RateLimitMiddleware
from sm_events.core import constants
from sm_events.feeds.tokens import resolve as resolve_module
from sm_events.feeds.tokens import service
from sm_events.models import FeedToken
from sm_events.web.endpoints.public import _private_feed
from sqlalchemy import select

from tests.support.app import as_user
from tests.support.calendars import seed_event
from tests.support.private_feed import (
    add_text,
    feed_path,
    invented,
    mint,
    private_http,
    seed_world,
)
from tests.support.tokens import NOW


def parse(response) -> icalendar.Calendar:
    return icalendar.Calendar.from_ical(response.content)


def uids(response) -> set[str]:
    return {str(c["UID"]) for c in parse(response).walk("VEVENT")}


async def test_serves_calendar():
    async with private_http() as http:
        world = await seed_world(http)
        got = await http.get(world.path)
        assert got.status_code == 200, got.text
        assert got.headers["content-type"] == "text/calendar; charset=utf-8"
        assert got.headers["cache-control"] == "private, no-store"
        assert got.headers["referrer-policy"] == "no-referrer"
        assert got.headers["x-robots-tag"] == "noindex"
        for banned in ("etag", "set-cookie", "vary", "content-disposition", "location"):
            assert banned not in got.headers, banned
        assert uids(got) == {world.pub.uid}  # the draft is not in a feed, whoever its owner is
        assert "Secret draft" not in got.text
        calendar = parse(got)
        assert str(calendar["X-WR-CALNAME"]) == world.cals["P"].name
        assert str(calendar["X-WR-TIMEZONE"]) == "UTC"


async def test_never_a_conditional_answer():
    """No validator is sent, and none is honoured: a 304 would be a second success shape."""
    async with private_http() as http:
        world = await seed_world(http)
        for header in (
            {"If-None-Match": "*"},
            {"If-None-Match": 'W/"x"'},
            {"If-Modified-Since": "x"},
        ):
            got = await http.get(world.path, headers=header)
            assert got.status_code == 200 and "etag" not in got.headers


async def test_head_matches_get_headers():
    async with private_http() as http:
        world = await seed_world(http)
        get, head = await http.get(world.path), await http.head(world.path)
        assert head.status_code == 200 and head.content == b""
        skip = {"date", "x-correlation-id"}
        assert {k: v for k, v in head.headers.items() if k not in skip} == {
            k: v for k, v in get.headers.items() if k not in skip
        }
        assert head.headers["content-length"] == str(len(get.content))


async def test_head_of_a_refusal_matches_its_get():
    async with private_http() as http:
        await seed_world(http)
        path = feed_path(invented())
        get, head = await http.get(path), await http.head(path)
        assert (head.status_code, head.content) == (404, b"")
        assert head.headers["content-length"] == str(len(get.content))
        assert head.headers["cache-control"] == get.headers["cache-control"] == "no-store"


async def test_locale_from_row():
    async with private_http(settings={"content_locales": ("en", "de")}) as http:
        world = await seed_world(http)
        await add_text(http, world.pub, "de", "Veroeffentlicht")
        german = await mint(http, world.cals["P"], locale="de")
        english = await http.get(world.path)
        assert "SUMMARY:Published" in english.text.replace("\r\n", "\n")
        got = await http.get(feed_path(german.secret))
        assert "SUMMARY:Veroeffentlicht" in got.text.replace("\r\n", "\n")
        assert "SUMMARY:Published" not in got.text.replace("\r\n", "\n")


async def test_url_property():
    """A public calendar's events link to their public page; any other, to the console."""
    async with private_http() as http:
        world = await seed_world(http)
        from sm_events.core.tenancy import tenant_scope

        with tenant_scope("default"):
            async with http.db_state.session_factory() as db:
                public = await seed_event(
                    db, world.cals["U"], title="Open", status="published", slug="open-day"
                )
                internal = await seed_event(
                    db, world.cals["I"], title="Staff", status="published", slug="staff-day"
                )
                await db.commit()
        public_feed = await mint(http, world.cals["U"])
        internal_feed = await mint(http, world.cals["I"])
        got = parse(await http.get(feed_path(public_feed.secret)))
        (component,) = list(got.walk("VEVENT"))
        assert str(component["URL"]) == "http://test/events/open-day"
        got = parse(await http.get(feed_path(internal_feed.secret)))
        (component,) = list(got.walk("VEVENT"))
        assert str(component["URL"]) == f"http://test/admin/events/edit/{internal.id}"
        assert public.uid != internal.uid


async def test_anonymous_and_signed_in_same_body():
    async with private_http() as http:
        world = await seed_world(http)
        anonymous = await http.get(world.path)
        signed = await http.get(world.path, headers=as_user("m", "events.view", "events.manage"))
        assert signed.content == anonymous.content
        assert signed.headers["cache-control"] == "private, no-store"


async def test_no_csrf_no_session_needed():
    async with private_http() as http:
        world = await seed_world(http)
        assert (await http.get(world.path)).status_code == 200
        assert (await http.post(world.path)).status_code == 405  # reads only


async def test_ip_rate_limit(monkeypatch):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        rules = http.app.state.rate_limit_rules
        for method in ("GET", "HEAD"):
            rule = rules.match(method, "/events/feed/x.ics")
            assert rule is not None and rule.rate == constants.FEED_PRIVATE_RATE, method
            assert rule.key == "ip"
        assert rules.match("POST", "/events/feed/x.ics") is None
        assert rules.match("GET", "/events/feed/a/b.ics") is None
        assert rules.match("GET", "/events/feedback/x.ics") is None
        http.app.add_middleware(RateLimitMiddleware, public_rate=None)
        for i in range(30):  # a different token each: the per-IP budget is the one in play
            assert (await http.get(feed_path(f"evf_{i:043d}"))).status_code == 404
        limited = await http.get(feed_path(f"evf_{30:043d}"))
        assert limited.status_code == 429 and "retry-after" in limited.headers


async def test_token_throttle_uniform(monkeypatch):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        looked_up = []
        real = _private_feed.lookup

        async def counting(db, token):
            looked_up.append(1)
            return await real(db, token)

        monkeypatch.setattr(_private_feed, "lookup", counting)
        fake = feed_path(invented("Y"))
        for _ in range(constants.FEED_TOKEN_RATE):
            assert (await http.get(world.path)).status_code == 200
            assert (await http.get(fake)).status_code == 404
        before = len(looked_up)
        valid_last, invented_last = await http.get(world.path), await http.get(fake)
        assert len(looked_up) == before  # refused before any lookup
        for got in (valid_last, invented_last):
            assert got.status_code == 429
            assert got.headers["cache-control"] == "no-store"
            assert int(got.headers["retry-after"]) >= 1
            assert got.headers["referrer-policy"] == "no-referrer"
        assert valid_last.content == invented_last.content
        skip = {"date", "retry-after", "x-correlation-id"}
        assert {k: v for k, v in valid_last.headers.items() if k not in skip} == {
            k: v for k, v in invented_last.headers.items() if k not in skip
        }
        assert world.secret.encode() not in valid_last.content


async def test_internal_error_is_503_without_token(monkeypatch, caplog):
    async with private_http() as http:
        world = await seed_world(http)

        async def boom(*_a, **_k):
            raise RuntimeError(f"directory down for {world.path}")

        monkeypatch.setattr(_private_feed, "resolve", boom)
        with caplog.at_level("DEBUG"):
            got = await http.get(world.path)
        assert got.status_code == 503
        assert got.headers["cache-control"] == "no-store"
        assert got.headers["referrer-policy"] == "no-referrer"
        assert got.json() == {"detail": "Service unavailable", "code": "service_unavailable"}
        server = [r for r in caplog.records if not r.name.startswith("http")]  # not the client's
        assert server and all(world.secret not in r.getMessage() for r in server)
        assert world.secret not in got.text
        assert "RuntimeError" in caplog.text


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
