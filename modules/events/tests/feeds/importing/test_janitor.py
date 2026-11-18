"""The janitor: expiry, relaunching lost work, revoked links; per tenant, counts only in the log."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.janitor import janitor_async
from sm_events.models import EventImport, EventImportItem, FeedToken
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.staging_support import make_import, seed
from tests.feeds.importing.write_support import make_item

NOW = utcnow()
DAY = timedelta(days=1)


_CALENDARS: dict[tuple[int, str], object] = {}


async def _calendar(db, state, tenant):
    key = (id(state), tenant)
    if key not in _CALENDARS:
        _CALENDARS[key] = (await seed(db))["P"]
    return _CALENDARS[key]


async def _import(state, tenant, status, *, age, lease=None, items=1, source=None):
    """An import in ``tenant`` last changed ``age`` ago, with staged items."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            calendar = await _calendar(db, state, tenant)
            imp = await make_import(
                db,
                calendar,
                status=status,
                data=source,
                updated_at=NOW - age,
                lease_until=None if lease is None else NOW + lease,
                lease_owner=None if lease is None else "w",
            )
            for n in range(items):
                await make_item(db, imp, seq=n + 1)
            await db.commit()
            return imp.id


async def _ids(state, tenant) -> set[int]:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            return set((await db.execute(select(EventImport.id))).scalars())


async def _items(state, tenant) -> int:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            return len((await db.execute(select(EventImportItem))).scalars().all())


class Relaunched(list):
    def __call__(self, tenant_id, import_id):
        self.append((tenant_id, import_id))


@pytest.fixture
def relaunch():
    return Relaunched()


async def test_expires_after_ttl(events_app, relaunch):
    _app, state = events_app
    old = constants.IMPORT_TTL + timedelta(hours=1)
    fresh = constants.IMPORT_TTL - timedelta(hours=1)
    gone = [await _import(state, "default", s, age=old) for s in ("staged", "done", "failed")]
    kept = [await _import(state, "default", s, age=fresh) for s in ("staged", "done", "failed")]
    summary = await janitor_async(state.session_factory, now=NOW, relaunch=relaunch)
    assert await _ids(state, "default") == set(kept)
    assert await _items(state, "default") == 3  # the expired imports' items went with them
    assert summary["deleted"] == 3 and not set(gone) & await _ids(state, "default")
    assert relaunch == []


async def test_relaunches_lost(events_app, relaunch):
    _app, state = events_app
    lost = constants.IMPORT_LEASE + timedelta(minutes=1)
    quiet = constants.IMPORT_LEASE - timedelta(minutes=1)
    stale = [
        await _import(state, "default", "uploaded", age=lost, source=corpus.simple()),
        await _import(state, "default", "queued", age=lost),
        await _import(
            state,
            "default",
            "parsing",
            age=lost,
            lease=-timedelta(minutes=1),
            source=corpus.simple(),
        ),
        await _import(state, "default", "running", age=lost, lease=-timedelta(minutes=1)),
    ]
    live = [
        await _import(state, "default", "uploaded", age=quiet, source=corpus.simple()),
        await _import(state, "default", "queued", age=quiet),
        await _import(
            state,
            "default",
            "parsing",
            age=lost,
            lease=timedelta(minutes=3),
            source=corpus.simple(),
        ),
        await _import(state, "default", "running", age=lost, lease=timedelta(minutes=3)),
    ]
    summary = await janitor_async(state.session_factory, now=NOW, relaunch=relaunch)
    assert sorted(i for _t, i in relaunch) == sorted(stale)
    assert not set(live) & {i for _t, i in relaunch}
    assert summary["relaunched"] == 4
    assert await _ids(state, "default") >= set(stale) | set(live)  # relaunching deletes nothing


async def test_sweeps_revoked_tokens(events_app, relaunch):
    from sm_events.models import Calendar

    _app, state = events_app
    with tenant_scope("default"):
        async with state.session_factory() as db:
            cal = Calendar(slug="c", name="C", owner_id="o")
            db.add(cal)
            await db.flush()
            for user, age in (("old", 31), ("recent", 29), ("live", None)):
                db.add(
                    FeedToken(
                        calendar_id=cal.id,
                        user_id=user,
                        token_hash=user.ljust(64, "0"),
                        label="L",
                        locale="en",
                        revoked_at=None if age is None else NOW - timedelta(days=age),
                    )
                )
            await db.commit()
    summary = await janitor_async(state.session_factory, now=NOW, relaunch=relaunch)
    assert summary["tokens"] == 1
    with tenant_scope("default"):
        async with state.session_factory() as db:
            left = set((await db.execute(select(FeedToken.user_id))).scalars())
    assert left == {"recent", "live"}


@pytest.mark.unbound_tenant
async def test_per_tenant(events_app, relaunch):
    _app, state = events_app
    old = constants.IMPORT_TTL + DAY
    a = await _import(state, "a", "done", age=old)
    b = await _import(state, "b", "done", age=old)
    kept = await _import(state, "b", "staged", age=DAY / 2)
    lost = await _import(state, "a", "queued", age=constants.IMPORT_LEASE + DAY)
    summary = await janitor_async(state.session_factory, now=NOW, relaunch=relaunch)
    assert summary["tenants"] == 2
    assert await _ids(state, "a") == {lost} and await _ids(state, "b") == {kept}
    assert relaunch == [("a", lost)]
    assert a != b


@pytest.mark.unbound_tenant
async def test_a_failure_in_one_tenant_does_not_stop_the_rest(events_app, relaunch, caplog):
    _app, state = events_app
    old = constants.IMPORT_TTL + DAY
    await _import(state, "a", "done", age=old)
    await _import(state, "b", "done", age=old)

    class Broken(Relaunched):
        def __call__(self, tenant_id, import_id):
            raise RuntimeError("broker down")

    await _import(state, "a", "queued", age=constants.IMPORT_LEASE + DAY)
    with caplog.at_level(logging.INFO):
        summary = await janitor_async(state.session_factory, now=NOW, relaunch=Broken())
    assert summary["deleted"] == 2 and summary["relaunched"] == 0


async def test_counts_only_in_log(events_app, relaunch, caplog):
    _app, state = events_app
    await _import(state, "default", "done", age=constants.IMPORT_TTL + DAY)
    with caplog.at_level(logging.DEBUG):
        await janitor_async(state.session_factory, now=NOW, relaunch=relaunch)
    text = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("sm_events"))
    assert "x.ics" not in text and "default" not in text
    assert "1 import(s) deleted" in text
