"""An upload cannot make a parse run for ever: matching, a budget, attempts, caps."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors import ImportBusy, ImportTenantBusy
from sm_events.feeds.importing import staging
from sm_events.feeds.importing.fence import claim
from sm_events.feeds.importing.janitor import janitor_async
from sm_events.models import EventImport, EventImportItem
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.mapping import mapped
from tests.feeds.importing.runner_support import read, run, stage
from tests.feeds.importing.staging_support import make_import, seed
from tests.support.access import principal

V, M = "events.view", "events.manage"


def far_series(n: int) -> list[str]:
    """The reviewer's shape: a daily series to 2125 with 700 EXDATEs near its end."""
    dates = ",".join(
        (datetime(2120, 1, 1, 9, tzinfo=UTC) + timedelta(days=d)).strftime("%Y%m%dT%H%M%SZ")
        for d in range(700)
    )
    lines: list[str] = []
    for i in range(n):
        lines += corpus.vevent(
            f"far{i}@x",
            "RRULE:FREQ=DAILY;UNTIL=21250101T000000Z",
            f"EXDATE:{dates}",
            start="20260101T090000Z",
            end="20260101T100000Z",
        )
    return lines


def test_far_exdates_cost_one_bounded_expansion_each():
    """Matching 700 EXDATEs a series costs about what the series costs without them (before, each
    EXDATE walked the rule on its own: 0.3 to 0.4 ms each)."""
    without = [line for line in far_series(12) if not line.startswith("EXDATE")]
    began = time.monotonic()
    mapped(*without)
    base = time.monotonic() - began
    began = time.monotonic()
    got = mapped(*far_series(12))
    with_exdates = time.monotonic() - began
    assert with_exdates < base * 1.6 + 1.0, (base, with_exdates)
    for item in got.items:
        assert item.event is not None and "exdate_ignored" in item.notes
        assert item.event.overrides == []  # beyond the expansion cap: not verified, so ignored


def test_exdates_within_reach_still_become_skips():
    lines = corpus.vevent(
        "near@x",
        "RRULE:FREQ=DAILY;COUNT=30",
        "EXDATE:20260105T090000Z,20260110T090000Z,20260301T090000Z",
        start="20260101T090000Z",
        end="20260101T100000Z",
    )
    (item,) = mapped(*lines).items
    assert [o.original_start.day for o in item.event.overrides] == [5, 10]  # type: ignore[union-attr]
    assert "exdate_ignored" in item.notes  # March is past COUNT=30


async def test_a_parse_over_its_budget_fails_with_too_complex(events_app, monkeypatch):
    _app, state = events_app
    monkeypatch.setattr(constants, "IMPORT_PARSE_SECONDS", 0.0)
    _cal, import_id = await stage(state, corpus.simple(50))
    assert await run(state, import_id) == "done"
    imp, items, _ = await read(state, import_id)
    assert (imp.status, imp.error_code, imp.source, items) == ("failed", "too_complex", None, [])


async def test_a_parse_that_keeps_dying_ends_for_good(events_app):
    """Every claim of an unfinished parse counts; past the limit the import is failed, never
    retried again."""
    _app, state = events_app
    _cal, import_id = await stage(state, corpus.simple(2))
    now = utcnow()
    for n in range(constants.IMPORT_PARSE_ATTEMPTS):  # three workers die mid-parse
        async with state.session_factory() as db:
            got = await claim(
                db,
                tenant_id="default",
                import_id=import_id,
                owner=f"dead{n}",
                now=now + constants.IMPORT_LEASE * (n + 1) * 2,
            )
            assert got.kind == "claimed"
            await db.commit()
    later = lambda: now + constants.IMPORT_LEASE * 100  # noqa: E731
    assert await run(state, import_id, now=later) == "done"
    imp, items, _ = await read(state, import_id)
    assert (imp.status, imp.error_code, imp.source, items) == ("failed", "too_complex", None, [])
    assert await run(state, import_id, now=later) == "gone"  # and nothing retries it


async def test_an_old_unfinished_parse_is_deleted_like_the_rest(events_app):
    _app, state = events_app
    _cal, _import_id = await stage(state, corpus.simple(1))
    async with state.session_factory() as db:
        row = (await db.execute(select(EventImport))).scalar_one()
        row.updated_at = utcnow() - constants.IMPORT_TTL - timedelta(hours=1)
        await db.commit()
    relaunched: list = []
    summary = await janitor_async(
        state.session_factory, now=utcnow(), relaunch=lambda t, i: relaunched.append(i)
    )
    assert summary["deleted"] == 1 and relaunched == []
    async with state.session_factory() as db:
        assert (await db.execute(select(EventImport))).scalars().all() == []
        assert (await db.execute(select(EventImportItem))).scalars().all() == []


async def test_the_active_cap_is_per_user_with_a_larger_one_per_tenant(db):
    cals = await seed(db)
    mine, theirs = principal("m", V, M), principal("m2", V, M)

    async def make(who, n=1):
        for _ in range(n):
            await staging.create_import(
                db,
                who,
                calendar_id=cals["P"].id,
                filename="a.ics",
                data=corpus.simple(),
                now=utcnow(),
            )

    await make(mine, constants.IMPORT_ACTIVE_MAX)
    with pytest.raises(ImportBusy):
        await make(mine)
    await make(theirs)  # one user at the cap does not block another
    for n in range(constants.IMPORT_ACTIVE_TENANT_MAX - constants.IMPORT_ACTIVE_MAX - 1):
        await make(principal(f"x{n}", V, M))
    with pytest.raises(ImportTenantBusy):  # the tenant's own ceiling
        await make(principal("last", V, M))


async def test_make_import_helper_is_used():
    assert make_import
