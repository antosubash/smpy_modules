"""``/api/events/public/*``: the anonymous routes the pagebuilder blocks read."""

from __future__ import annotations

import uuid
from urllib.parse import urlencode

import pytest
from sm_events.content import calendar_redirects
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, Visibility
from sm_events.web.endpoints.public import _urls
from sqlalchemy import update

from tests.support.app import as_user
from tests.support.public import seed_public, tenant_header
from tests.web.public.leaks import assert_no_event_ids

API = constants.PUBLIC_BLOCKS_API
CALENDARS, UPCOMING, OCCURRENCES = f"{API}/calendars", f"{API}/upcoming", f"{API}/occurrences"
YEAR = "start=2026-01-01T00:00:00Z&end=2026-12-31T00:00:00Z"


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client, german=False)


def qs(**pairs) -> str:
    out: list[tuple[str, str]] = []
    for key, value in pairs.items():
        out += [(key, str(v)) for v in (value if isinstance(value, list) else [value])]
    return urlencode(out)


async def _update(client, model, where, **values):
    with tenant_scope("default"):
        async with client.db_state.session_factory() as db:
            await db.execute(update(model).where(where).values(**values))
            await db.commit()


async def test_calendars_all_and_by_slug(public_locales_client, fx):
    everything = (await public_locales_client.get(CALENDARS)).json()
    assert [c["slug"] for c in everything["calendars"]] == [fx.pub.slug]
    chosen = (
        await public_locales_client.get(
            f"{CALENDARS}?{qs(calendar=[fx.pub.slug, fx.internal.slug, 'nope'])}"
        )
    ).json()
    assert [c["slug"] for c in chosen["calendars"]] == [fx.pub.slug]
    (cal,) = chosen["calendars"]
    assert set(cal) == {"id", "slug", "name", "color", "default_timezone"}
    assert cal["id"] == str(fx.pub.id)
    assert chosen["default_timezone"] == cal["default_timezone"]


async def test_an_old_slug_resolves_through_the_redirects(public_locales_client, fx):
    old = fx.pub.slug
    with tenant_scope("default"):
        async with public_locales_client.db_state.session_factory() as db:
            await db.execute(
                update(Calendar).where(Calendar.id == fx.pub.id).values(slug="renamed")
            )
            await calendar_redirects.record_rename(db, calendar_id=fx.pub.id, old_slug=old)
            await db.commit()
    got = (await public_locales_client.get(f"{CALENDARS}?{qs(calendar=[old])}")).json()
    assert [c["slug"] for c in got["calendars"]] == ["renamed"]


async def test_calendar_turned_internal_vanishes_without_name(public_locales_client, fx):
    await _update(
        public_locales_client, Calendar, Calendar.id == fx.pub.id, visibility=Visibility.INTERNAL
    )
    for url in (f"{CALENDARS}?{qs(calendar=[fx.pub.slug])}", CALENDARS):
        got = await public_locales_client.get(url)
        assert got.json()["calendars"] == []
        assert fx.pub.slug not in got.text and fx.pub.name not in got.text
    upcoming = await public_locales_client.get(f"{UPCOMING}?{qs(calendar=[fx.pub.slug])}")
    assert upcoming.json() == {"items": []}


async def test_categories_only_public(public_locales_client, fx):
    got = (await public_locales_client.get(f"{CALENDARS}?locale=de")).json()
    slugs = [c["slug"] for c in got["categories"]]
    assert slugs == [fx.public_cat.slug]  # the draft's category is used by no public event
    assert set(got["categories"][0]) == {"id", "slug", "name", "color"}
    assert got["categories"][0]["name"] == fx.public_cat.slug  # no German name: the default's


async def test_upcoming_count_and_bounds(public_locales_client, fx):
    three = (await public_locales_client.get(f"{UPCOMING}?count=3")).json()["items"]
    assert len(three) == 3
    starts = [i["start_local"] for i in three]
    assert starts == sorted(starts)
    default = (await public_locales_client.get(UPCOMING)).json()["items"]
    assert len(default) == constants.UPCOMING_BLOCK_DEFAULT
    for bad in ("0", "21", "x", "-1", "1.5", ""):
        got = await public_locales_client.get(f"{UPCOMING}?count={bad}")
        assert got.status_code == 422, bad
        assert got.json() == {"detail": constants.INVALID_QUERY_DETAIL, "code": "invalid_query"}
        assert got.headers["cache-control"] == "no-store"
    too_many = (
        f"{UPCOMING}?{qs(calendar=[f'c{i}' for i in range(constants.BLOCK_CALENDARS_MAX + 1)])}"
    )
    assert (await public_locales_client.get(too_many)).status_code == 422


async def test_upcoming_selection_rules(public_locales_client, fx):
    every = (await public_locales_client.get(f"{UPCOMING}?count=20")).json()["items"]
    assert len(every) > 5
    none = await public_locales_client.get(f"{UPCOMING}?{qs(calendar=[fx.internal.slug])}")
    assert none.json() == {"items": []}  # resolves to nothing: nothing, never "all"
    unknown_cat = await public_locales_client.get(f"{UPCOMING}?category=no-such&count=20")
    assert unknown_cat.json() == {"items": []}
    draft_cat = await public_locales_client.get(f"{UPCOMING}?category={fx.draft_cat.slug}")
    assert draft_cat.json() == {"items": []}
    cat = await public_locales_client.get(f"{UPCOMING}?category={fx.public_cat.slug}")
    assert [i["title"] for i in cat.json()["items"]] == [fx.slug(fx.one_off).title()]


async def test_upcoming_items(public_locales_client, fx):
    await _update(
        public_locales_client,
        Event,
        Event.id == fx.one_off.id,
        image="/media/a.png",
    )
    await _update(public_locales_client, Event, Event.id == fx.conf.id, image="javascript:alert(1)")
    got = (await public_locales_client.get(f"{UPCOMING}?count=20&locale=de")).json()["items"]
    by_title = {i["title"]: i for i in got}
    one = by_title[fx.slug(fx.one_off, "de").title()]
    assert one["image"] == "/media/a.png"
    conf = by_title[fx.slug(fx.conf).title()]
    assert conf["image"] is None and conf["lang"] == "en"  # a fallback text, marked
    series = [i for i in got if i["title"] == fx.slug(fx.series, "de").title()]
    cancelled = next(i for i in series if i["url"].endswith("date=2026-04-06"))
    assert cancelled["status"] == "cancelled"
    assert all("?date=" in i["url"] for i in series)


async def test_occurrences_alias_matches_the_public_api(public_locales_client, fx):
    one = await public_locales_client.get(f"{OCCURRENCES}?{YEAR}&calendar={fx.pub.id}")
    two = await public_locales_client.get(f"{_urls.api_path()}?{YEAR}&calendar={fx.pub.id}")
    assert one.status_code == 200 and one.json() == two.json()
    assert (await public_locales_client.get(f"{OCCURRENCES}?start=x")).json()["code"] == (
        "invalid_query"
    )


async def test_no_event_ids_anywhere(public_locales_client, fx):
    for url in (CALENDARS, f"{UPCOMING}?count=20", f"{OCCURRENCES}?{YEAR}"):
        got = await public_locales_client.get(url)
        assert got.status_code == 200
        assert_no_event_ids(got.text, fx)


@pytest.mark.unbound_tenant
async def test_anonymous_get_head_and_no_other_method(public_locales_client, fx):
    for url in (CALENDARS, UPCOMING, f"{OCCURRENCES}?{YEAR}"):
        get = await public_locales_client.get(url)
        head = await public_locales_client.head(url)
        assert get.status_code == head.status_code == 200
        assert head.content == b"" and head.headers["content-length"] == str(len(get.content))
        assert get.headers["cache-control"] == "public, max-age=60"
        assert "etag" in get.headers
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            assert (await public_locales_client.request(method, url)).status_code == 405, method


async def test_signed_in_manager_sees_public_only(public_locales_client, fx):
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for url in (CALENDARS, f"{UPCOMING}?count=20"):
        anon = await public_locales_client.get(url)
        signed = await public_locales_client.get(url, headers=manager)
        assert signed.json() == anon.json()
        assert signed.headers["cache-control"].startswith("private")


async def test_conditional_get(public_locales_client, fx):
    got = await public_locales_client.get(CALENDARS)
    again = await public_locales_client.get(
        CALENDARS, headers={"If-None-Match": got.headers["etag"]}
    )
    assert again.status_code == 304 and again.content == b""


async def test_etag_only_over_visible_body(public_locales_client, fx):
    """A guessed validator on a hidden calendar's slug is a 200 with an empty list, and its tag is
    the one an unknown slug gets: nothing tells a hidden calendar from one that never existed."""
    hidden = f"{CALENDARS}?{qs(calendar=[fx.internal.slug])}"
    unknown = f"{CALENDARS}?{qs(calendar=['no-such-calendar'])}"
    got = await public_locales_client.get(hidden, headers={"If-None-Match": 'W/"guess"'})
    assert got.status_code == 200 and got.json()["calendars"] == []
    gone = await public_locales_client.get(unknown)
    assert got.headers["etag"] == gone.headers["etag"]


@pytest.mark.unbound_tenant
async def test_request_tenant_never_shareable_two_tenants_two_etags(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a", german=False)
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b", german=False)
    a = await public_multi_client.get(UPCOMING, headers=tenant_header("a"))
    b = await public_multi_client.get(UPCOMING, headers=tenant_header("b"))
    for got, own, other in ((a, mine, theirs), (b, theirs, mine)):
        assert got.status_code == 200
        assert got.headers["cache-control"].startswith("private")
        assert "cookie" in got.headers["vary"].lower()
        assert own.slug(own.one_off) in got.text or own.slug(own.series) in got.text
        assert other.slug(other.one_off) not in got.text
    assert a.headers["etag"] != b.headers["etag"]
    cals = await public_multi_client.get(CALENDARS, headers=tenant_header("a"))
    assert [c["slug"] for c in cals.json()["calendars"]] == [mine.pub.slug]
    cross = await public_multi_client.get(
        f"{CALENDARS}?{qs(calendar=[theirs.pub.slug])}", headers=tenant_header("a")
    )
    assert cross.json()["calendars"] == []


@pytest.mark.unbound_tenant
async def test_no_tenant_is_a_404_without_a_query(public_multi_client):
    for url in (CALENDARS, UPCOMING, f"{OCCURRENCES}?{YEAR}"):
        got = await public_multi_client.get(url)
        assert got.status_code == 404 and got.headers["cache-control"] == "no-store"
        assert "etag" not in got.headers


async def test_exempt_from_auth_and_rate_limited(public_locales_client):
    from simple_module_hosting.public_access import is_public

    app = public_locales_client.app
    for path in (CALENDARS, UPCOMING, OCCURRENCES):
        assert is_public(app, "GET", path) and is_public(app, "HEAD", path)
        assert not is_public(app, "POST", path)
        rule = app.state.rate_limit_rules.match("GET", path)
        assert rule is not None and rule.rate == constants.PUBLIC_API_RATE and rule.key == "ip"
    assert not is_public(app, "GET", f"{constants.ROUTE_PREFIX_API}/events")


def test_the_constants_are_ruled():
    assert constants.PUBLIC_BLOCKS_API == "/api/events/public"
    assert (constants.UPCOMING_BLOCK_MAX, constants.UPCOMING_BLOCK_DEFAULT) == (20, 5)
    assert constants.BLOCK_CALENDARS_MAX == 10


async def _all(client, query: str):
    """The three routes for one selection: (calendars, upcoming items, occurrence items)."""
    cal = (await client.get(f"{CALENDARS}?{query}")).json()["calendars"]
    up = (await client.get(f"{UPCOMING}?count=20&{query}")).json()["items"]
    return cal, up


async def test_a_selection_that_resolves_to_nothing_shows_nothing_on_every_route(
    public_locales_client, fx
):
    """The rule, in effect: unknown slugs, only non-public calendars, a malformed slug or an empty
    one is *nothing*, never every public calendar; one valid slug beside an unknown one is just the
    valid one."""
    for query in (
        qs(calendar=["nope"]),
        qs(calendar=["nope", "also-not-there"]),
        qs(calendar=[fx.internal.slug]),
        qs(calendar=[fx.private.slug, fx.gone.slug]),
        qs(calendar=["Not A Slug!"]),
        "calendar=",
    ):
        cal, up = await _all(public_locales_client, query)
        assert cal == [] and up == [], query
    cal, up = await _all(public_locales_client, qs(calendar=[fx.pub.slug, "nope"]))
    assert [c["slug"] for c in cal] == [fx.pub.slug]
    assert up and {i["calendar"]["slug"] for i in up} == {fx.pub.slug}
    everything = await _all(public_locales_client, "")
    assert len(everything[0]) == 1 and everything[1]  # no selection: every public calendar

    for ids in (
        [uuid.uuid4()],
        [fx.internal.id],
        [fx.private.id, fx.gone.id],
    ):
        got = await public_locales_client.get(f"{OCCURRENCES}?{YEAR}&{qs(calendar=ids)}")
        assert got.status_code == 200 and got.json()["items"] == [], ids
    mixed = await public_locales_client.get(
        f"{OCCURRENCES}?{YEAR}&{qs(calendar=[fx.pub.id, uuid.uuid4()])}"
    )
    assert mixed.json()["items"], "the valid calendar's events"
    assert {i["calendar_id"] for i in mixed.json()["items"]} == {str(fx.pub.id)}


async def test_the_read_is_never_asked_for_every_calendar_when_a_selection_was_given(
    public_locales_client, fx, monkeypatch
):
    """A refactor to ``calendar_ids=None`` would turn "nothing" into "everything": the downstream
    reads are spied on, and none gets ``None`` (or is called at all) for a selection."""
    from sm_events.web.endpoints.public import _api, _blocks_api

    seen: list[tuple[str, object]] = []
    real_upcoming, real_page = _blocks_api.upcoming, _api.public_page

    async def upcoming(db, **kw):
        seen.append(("upcoming", kw["calendar_ids"]))
        return await real_upcoming(db, **kw)

    async def page(db, **kw):
        seen.append(("occurrences", kw["calendar_ids"]))
        return await real_page(db, **kw)

    monkeypatch.setattr(_blocks_api, "upcoming", upcoming)
    monkeypatch.setattr(_api, "public_page", page)

    for slugs in (["nope"], [fx.internal.slug], ["nope", fx.pub.slug], ["Not A Slug!"], [""]):
        seen.clear()
        await public_locales_client.get(f"{UPCOMING}?{qs(calendar=slugs)}")
        assert all(ids is not None for _, ids in seen), slugs  # not called, or given a list
    seen.clear()
    await public_locales_client.get(f"{UPCOMING}")
    assert seen == [("upcoming", None)]  # no selection: every public calendar, and only then
    seen.clear()
    await public_locales_client.get(f"{OCCURRENCES}?{YEAR}&{qs(calendar=[uuid.uuid4()])}")
    assert [ids is not None for _, ids in seen] == [True]
