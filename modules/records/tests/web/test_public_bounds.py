"""The public listing's own bounds (#349): fewer filter terms, one ``contains``,
and a Postgres statement timeout that answers 503 rather than 500.

The admin listing keeps ``max_filter_terms``; only the anonymous surface (the
listing and its stats block) is narrowed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sm_records.records.services import public_bounds
from sm_records.records.services.public_bounds import (
    PUBLIC_MAX_CONTAINS_TERMS,
    PUBLIC_MAX_FILTER_TERMS,
    PublicQueryTimedOut,
    statement_timeout,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from tests.pg_support import USING_POSTGRES
from tests.support.app_harness import ADMIN, roles

_API = "/api/records/types/post/records"
_PUBLIC = "/api/records/public/post"


def _field(key: str) -> dict:
    return {"key": key, "type": "text", "label": key.title(), "indexed": True}


@pytest_asyncio.fixture
async def seeded(client):
    resp = await client.post(
        "/api/records/types",
        json={
            "key": "post",
            "label": "Post",
            "fields": [_field("title"), _field("body"), _field("tag")],
            "display_field": "title",
            "is_public": True,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    for i in range(3):
        made = await client.post(
            _API,
            json={"data": {"title": f"t{i}", "body": "b", "tag": "x"}, "status": "published"},
            headers=roles(ADMIN),
        )
        assert made.status_code == 201, made.text
    await client.app.state.records_module.on_startup(client.app)
    return client


def _query(*terms: str) -> str:
    return "&".join(f"filter={term}" for term in terms)


@pytest.mark.parametrize("url", [_PUBLIC, f"{_PUBLIC}/stats"])
async def test_three_terms_with_one_contains_are_answered(seeded, url):
    assert PUBLIC_MAX_FILTER_TERMS == 3 and PUBLIC_MAX_CONTAINS_TERMS == 1
    resp = await seeded.get(f"{url}?{_query('title:contains:t', 'body:eq:b', 'tag:eq:x')}")
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("url", [_PUBLIC, f"{_PUBLIC}/stats"])
async def test_a_fourth_term_is_refused_with_a_code(seeded, url):
    resp = await seeded.get(f"{url}?{_query('title:eq:t0', 'body:eq:b', 'tag:eq:x', 'tag:ne:y')}")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "too_many_filters"
    assert "no-store" in resp.headers["cache-control"]


@pytest.mark.parametrize("url", [_PUBLIC, f"{_PUBLIC}/stats"])
async def test_past_the_admin_cap_is_still_the_public_code(seeded, url):
    """25 terms is over ``max_filter_terms`` (20) too; the public cap answers first."""
    resp = await seeded.get(f"{url}?{_query(*(['title:eq:t0'] * 25))}")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "too_many_filters"


async def test_the_admin_listing_keeps_its_bare_cap(seeded):
    resp = await seeded.get(f"{_API}?{_query(*(['title:eq:t0'] * 25))}", headers=roles(ADMIN))
    assert resp.status_code == 400, resp.text
    assert "code" not in resp.json()


@pytest.mark.parametrize("url", [_PUBLIC, f"{_PUBLIC}/stats"])
async def test_a_second_contains_is_refused_with_a_code(seeded, url):
    resp = await seeded.get(f"{url}?{_query('title:contains:t', 'body:contains:b')}")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "too_many_contains"


async def test_the_admin_listing_keeps_its_own_caps(seeded):
    query = _query(*(["title:contains:t"] * 5))
    resp = await seeded.get(f"{_API}?{query}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 3


def _cancelled() -> DBAPIError:
    return OperationalError("SELECT 1", {}, SimpleNamespace(sqlstate="57014"))


@pytest.mark.parametrize("url", [_PUBLIC, f"{_PUBLIC}/stats"])
async def test_a_cancelled_statement_is_a_503_not_a_500(seeded, url, monkeypatch):
    """However the backend cancels it, ``statement_timeout`` maps SQLSTATE
    57014 to the envelope, and the public route class rolls back and adds
    ``no-store``."""
    real = public_bounds.statement_timeout

    def failing(db):
        manager = real(db)

        class _Fail:
            async def __aenter__(self):
                await manager.__aenter__()

            async def __aexit__(self, *exc):
                return await manager.__aexit__(DBAPIError, _cancelled(), None)

        return _Fail()

    from sm_records.records.services import public, public_stats

    monkeypatch.setattr(public, "statement_timeout", failing)
    monkeypatch.setattr(public_stats, "statement_timeout", failing)
    resp = await seeded.get(url)
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "query_timeout"
    assert "no-store" in resp.headers["cache-control"]


async def test_a_timeout_after_the_listing_is_a_503_too(seeded, monkeypatch):
    """``SET LOCAL`` outlives the listing call, so the translation lookup that
    follows it can be the statement cancelled; the route maps that as well."""
    from sm_records.records.services import public

    async def cancelled(*args, **kwargs):
        raise _cancelled()

    monkeypatch.setattr(public, "published_siblings", cancelled)
    resp = await seeded.get(_PUBLIC)
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "query_timeout"
    assert "no-store" in resp.headers["cache-control"]


async def test_an_admin_cancel_stays_a_500(seeded, monkeypatch):
    """Only the public router sets the timeout; an admin route keeps its logged 500."""
    from sm_records.records.services import records as record_service

    async def cancelled(*args, **kwargs):
        raise _cancelled()

    monkeypatch.setattr(record_service, "list_records", cancelled)
    resp = await seeded.get(_API, headers=roles(ADMIN))
    assert resp.status_code == 500, resp.text
    assert resp.json() == {"detail": "internal error"}


async def test_another_database_error_is_not_a_timeout(db):
    with pytest.raises(OperationalError):
        async with statement_timeout(db):
            raise OperationalError("SELECT 1", {}, SimpleNamespace(sqlstate="40001"))


async def test_the_timeout_is_set_only_off_sqlite(db, monkeypatch):
    seen: list[str] = []
    original = db.execute

    async def spy(statement, *args, **kwargs):
        seen.append(str(statement))
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", spy)
    async with statement_timeout(db):
        pass
    expected = [] if not USING_POSTGRES else ["SET LOCAL statement_timeout = 5000"]
    assert seen == expected


@pytest.mark.skipif(not USING_POSTGRES, reason="statement_timeout is a Postgres setting")
async def test_postgres_cancels_a_slow_statement(db, monkeypatch):
    monkeypatch.setattr(public_bounds, "PUBLIC_STATEMENT_TIMEOUT_MS", 50)
    with pytest.raises(PublicQueryTimedOut):
        async with statement_timeout(db):
            await db.execute(text("SELECT pg_sleep(2)"))
    await db.rollback()
