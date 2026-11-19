"""``GET /events/api/occurrences``: the public read for the read-only grid."""

from __future__ import annotations

import uuid

import pytest
from sm_events.core import constants
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.public import seed_public, tenant_header

YEAR = "start=2026-01-01T00:00:00Z&end=2026-12-31T00:00:00Z"
API = _urls.api_path()


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client, german=False)


def items(response) -> list[dict]:
    return response.json()["items"]


def by_title(response, title: str) -> list[dict]:
    return [i for i in items(response) if i["title"] == title]


async def test_shape_and_urls(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}")
    assert got.status_code == 200 and got.json()["truncated"] is False
    (one,) = by_title(got, fx.slug(fx.one_off).title())
    assert one["url"] == f"/events/{fx.slug(fx.one_off)}" and one["lang"] == "en"
    series = by_title(got, fx.slug(fx.series).title())
    assert len(series) == 7  # eight weeks, one skipped
    first = min(series, key=lambda i: i["start"])
    assert first["url"] == f"/events/{fx.slug(fx.series)}?date=2026-03-16"
    assert {i["url"] for i in series} == {
        f"/events/{fx.slug(fx.series)}?date={d}"
        for d in (
            "2026-03-16",
            "2026-03-23",
            "2026-03-30",
            "2026-04-06",
            "2026-04-20",
            "2026-04-27",
            "2026-05-04",
        )
    }
    assert all(i["editable"] is False and i["event_status"] == "published" for i in items(got))


async def test_no_internal_fields(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}")
    for item in items(got):
        assert item["event_id"] is None and item["original_start"] is None
        assert set(item) == {
            "source", "key", "calendar_id", "start", "end", "all_day", "timezone", "start_date",
            "end_date", "title", "lang", "color", "url", "status", "type", "editable", "event_id",
            "original_start", "event_status", "origin_label",
        }  # fmt: skip
    assert "draft" not in got.text.lower() and "in_review" not in got.text


async def test_moved_keeps_original_date(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}")
    moved = next(
        i for i in by_title(got, fx.slug(fx.series).title()) if i["url"].endswith("2026-03-30")
    )
    assert moved["start"].startswith("2026-03-30T09:00")  # 11:00 CEST, an hour later than 10:00
    cancelled = next(
        i for i in by_title(got, fx.slug(fx.series).title()) if i["url"].endswith("2026-04-06")
    )
    assert cancelled["status"] == "cancelled"


async def test_language_fallback_is_marked(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}&locale=de")
    (conf,) = by_title(got, fx.slug(fx.conf).title())
    assert conf["lang"] == "en" and conf["url"] == f"/events/{fx.slug(fx.conf)}"
    (one,) = by_title(got, fx.slug(fx.one_off, "de").title())
    assert one["lang"] == "de" and one["url"] == f"/de/events/{fx.slug(fx.one_off, 'de')}"
    unknown = await public_locales_client.get(f"{API}?{YEAR}&locale=zz")
    assert by_title(unknown, fx.slug(fx.one_off).title())  # an unknown language is the default


async def test_hidden_rows_are_absent(public_locales_client, fx):
    text = (await public_locales_client.get(f"{API}?{YEAR}")).text
    for event in fx.hidden.values():
        assert fx.slug(event) not in text and event.uid not in text


async def test_bounds(public_locales_client, fx):
    naive = await public_locales_client.get(
        f"{API}?start=2026-01-01T00:00:00&end=2026-02-01T00:00:00Z"
    )
    assert naive.status_code == 422 and naive.headers["cache-control"] == "no-store"
    long = await public_locales_client.get(
        f"{API}?start=2026-01-01T00:00:00Z&end=2027-01-03T00:00:00Z"
    )
    assert (long.status_code, long.json()["code"]) == (422, "range_too_long")
    assert long.headers["cache-control"] == "no-store" and "etag" not in long.headers
    back = await public_locales_client.get(
        f"{API}?start=2026-02-01T00:00:00Z&end=2026-01-01T00:00:00Z"
    )
    assert back.json()["code"] == "invalid_range"
    assert (await public_locales_client.get(f"{API}?start=2026-01-01T00:00:00Z")).status_code == 422


async def test_a_bad_query_is_the_json_envelope(public_locales_client, fx):
    """Missing and garbage parameters answer ``{"detail", "code"}`` with ``no-store``, not the
    host's HTML 422 page."""
    for query in (
        "",
        "start=x&end=y",
        "start=2026-01-01T00:00:00Z",
        f"{YEAR}&calendar=not-a-uuid",
        f"{YEAR}&category=1",
    ):
        got = await public_locales_client.get(f"{API}?{query}")
        assert got.status_code == 422, query
        assert got.headers["content-type"].startswith("application/json"), query
        assert got.json() == {"detail": constants.INVALID_QUERY_DETAIL, "code": "invalid_query"}
        assert got.headers["cache-control"] == "no-store", query


async def test_truncated_is_serialised(public_locales_client, fx, monkeypatch):
    monkeypatch.setattr(constants, "MAX_OCCURRENCES", 3)
    got = await public_locales_client.get(f"{API}?{YEAR}")
    assert got.json()["truncated"] is True and len(items(got)) == 3


async def test_calendar_ids_silently_dropped(public_locales_client, fx):
    empty = {"items": [], "truncated": False}
    for calendar in (fx.internal.id, fx.private.id, fx.gone.id, uuid.uuid4()):
        got = await public_locales_client.get(f"{API}?{YEAR}&calendar={calendar}")
        assert got.status_code == 200 and got.json() == empty, calendar
    ok = await public_locales_client.get(f"{API}?{YEAR}&calendar={fx.pub.id}")
    assert len(items(ok)) > 5
    mixed = await public_locales_client.get(
        f"{API}?{YEAR}&calendar={fx.pub.id}&calendar={fx.internal.id}"
    )
    assert items(mixed) == items(ok)


async def test_category_filter(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}&category={fx.public_cat.id}")
    assert [i["title"] for i in items(got)] == [fx.slug(fx.one_off).title()]
    hidden = await public_locales_client.get(f"{API}?{YEAR}&category={fx.draft_cat.id}")
    assert items(hidden) == []


async def test_type_is_accepted_and_ignored(public_locales_client, fx):
    plain = await public_locales_client.get(f"{API}?{YEAR}")
    typed = await public_locales_client.get(f"{API}?{YEAR}&type=conference")
    assert typed.json() == plain.json()


async def test_signed_in_manager_sees_public_only(public_locales_client, fx):
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    anon = await public_locales_client.get(f"{API}?{YEAR}")
    signed = await public_locales_client.get(f"{API}?{YEAR}", headers=manager)
    assert signed.json() == anon.json()
    assert signed.headers["cache-control"].startswith("private")


@pytest.mark.unbound_tenant
async def test_cache_and_etag(public_locales_client, fx):
    got = await public_locales_client.get(f"{API}?{YEAR}")
    assert got.headers["cache-control"] == "public, max-age=60"
    tag = got.headers["etag"]
    again = await public_locales_client.get(f"{API}?{YEAR}", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["cache-control"] == got.headers["cache-control"]


async def test_head(public_locales_client, fx):
    get = await public_locales_client.get(f"{API}?{YEAR}")
    head = await public_locales_client.head(f"{API}?{YEAR}")
    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-length"] == str(len(get.content))


async def test_only_on_the_default_prefix(public_locales_client, fx):
    assert (
        await public_locales_client.get(f"/de/events/api/occurrences?{YEAR}")
    ).status_code == 404


@pytest.mark.unbound_tenant
async def test_tenant_scoped_and_404_without_one(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a", german=False)
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b", german=False)
    got = await public_multi_client.get(f"{API}?{YEAR}", headers=tenant_header("a"))
    assert got.status_code == 200 and got.headers["cache-control"].startswith("private")
    assert theirs.slug(theirs.one_off) not in got.text and mine.slug(mine.one_off) in got.text
    nobody = await public_multi_client.get(f"{API}?{YEAR}")
    assert nobody.status_code == 404 and nobody.headers["cache-control"] == "no-store"
    cross = await public_multi_client.get(
        f"{API}?{YEAR}&calendar={theirs.pub.id}", headers=tenant_header("a")
    )
    assert cross.json() == {"items": [], "truncated": False}
