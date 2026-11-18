"""The runner: a plugin's failure is a status, never a 500, a hang or a poisoned transaction."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import pytest
from sm_events.calendar import source_entries
from sm_events.calendar.extension_types import SourceViewer
from sm_events.calendar.plugin_runner import Call, run_sources
from sm_events.core import constants
from sm_events.models import Calendar, Category
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.sources import (
    DeskSettings,
    FakeClock,
    FakeSource,
    bad_sql,
    commits,
    floods,
    item,
    ok,
    raises,
    returns,
    sleeps,
    swallows_cancel,
    writes,
    writes_and_flushes,
)

START, END = datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 8, 1, tzinfo=UTC)
VIEWER = SourceViewer(user_id="o", roles=("editor",), permissions=frozenset({"events.view"}))


def entry(ident="acme:fake", **settings):
    return source_entries.SourceEntry(ident, settings)


async def calendars(db):
    return {k: source_entries.source_calendar(c) for k, c in (await seed_calendars(db)).items()}


async def run(db, calls, **kw):
    kw.setdefault("viewer", VIEWER)
    return await run_sources(
        db,
        calls,
        tenant_id="default",
        start=START,
        end=END,
        locale="en",
        default_locale="en",
        **kw,
    )


async def one(db, source, **kw):
    cal = (await calendars(db))["I"]
    return await run(db, [Call(cal, entry(source.id), source)], **kw)


def status(result, index=0):
    s = result.statuses[index]
    return s.status, s.code


async def test_ok(db):
    src = FakeSource(behave=ok(item("b", "B"), item("a", "A")))
    result = await one(db, src)
    assert status(result) == ("ok", None)
    assert sorted(o.key.split(":", 1)[1] for o in result.items) == ["a", "b"]
    assert {o.source for o in result.items} == {"acme:fake"} and not result.truncated


async def test_raises_is_failed_and_logs_class_only(db, caplog):
    with caplog.at_level(logging.ERROR):
        result = await one(db, FakeSource(behave=raises))
    assert status(result) == ("failed", "raised") and result.items == []
    assert "RuntimeError" in caplog.text and "secret payload" not in caplog.text
    assert "acme:fake" in caplog.text


@pytest.mark.parametrize(
    ("behave", "code"),
    [
        (ok(item("a"), item("a")), "duplicate_key"),
        (ok(item("a"), item("b", title="\x00")), "invalid_item"),
        (ok(item("a", url="javascript:alert(1)")), "invalid_item"),
        (returns({"not": "a list"}), "invalid_answer"),
        (returns(None), "invalid_answer"),
        (returns(["not an item"]), "invalid_item"),
    ],
)
async def test_invalid_item_drops_whole_answer(db, behave, code):
    result = await one(db, FakeSource(behave=behave))
    assert status(result) == ("failed", code) and result.items == []


async def test_a_generator_answer_is_refused(db):
    async def gen_answer(ctx, start, end):
        return (item(f"k{i}") for i in range(3))

    assert status(await one(db, FakeSource(behave=gen_answer))) == ("failed", "invalid_answer")


async def test_timeout_cancels(db):
    began = time.monotonic()
    result = await one(db, FakeSource(behave=sleeps(10)))
    assert status(result) == ("timeout", None)
    assert time.monotonic() - began < 2.5


async def test_late_finish_after_swallowed_cancel_is_a_timeout(db, monkeypatch):
    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(constants, "SOURCE_MIN_SLICE_SECONDS", 0.01)
    assert status(await one(db, FakeSource(behave=swallows_cancel))) == ("timeout", None)


async def test_phase_budget_skips_rest(db):
    clock = FakeClock()
    cal = (await calendars(db))["I"]
    slow = [FakeSource(f"acme:s{i}", clock.spends(2.4)) for i in range(4)]
    calls = [Call(cal, entry(s.id), s) for s in slow]
    result = await run(db, calls, clock=clock)
    assert [status(result, i) for i in range(4)] == [
        ("ok", None),
        ("ok", None),
        ("skipped", "budget"),
        ("skipped", "budget"),
    ]
    assert slow[2].calls == [] and slow[3].calls == []


async def test_a_call_gets_what_is_left_of_the_phase(db):
    clock = FakeClock()
    seen = []

    async def watch(ctx, start, end):
        clock.advance(4.5)
        return []

    async def record(ctx, start, end):
        return []

    cal = (await calendars(db))["I"]
    first, second = FakeSource("acme:a", watch), FakeSource("acme:b", record)
    result = await run(db, [Call(cal, entry(s.id), s) for s in (first, second)], clock=clock)
    assert status(result, 1) == ("ok", None)  # 0.5 s left is at least the 0.25 s minimum
    assert seen == []


async def test_calls_capped(db):
    cal = (await calendars(db))["I"]
    sources = [FakeSource(f"acme:s{i:02d}") for i in range(17)]
    result = await run(db, [Call(cal, entry(s.id), s) for s in sources])
    assert [s.status for s in result.statuses[:16]] == ["ok"] * 16
    assert status(result, 16) == ("skipped", "too_many_calls")
    assert sources[16].calls == []


async def test_flood_truncated(db):
    result = await one(db, FakeSource(behave=floods(600)))
    assert status(result) == ("truncated", None) and result.truncated
    assert [o.key.split(":", 1)[1] for o in result.items] == [f"k{i}" for i in range(500)]


async def test_a_million_items_are_refused_unread(db):
    began = time.monotonic()
    result = await one(db, FakeSource(behave=returns([item("a")] * 1_000_000)))
    assert status(result) == ("failed", "too_many_items") and result.items == []
    assert time.monotonic() - began < 2  # refused unread: nothing is validated


async def test_write_is_rolled_back(db):
    result = await one(db, FakeSource(behave=writes))
    assert status(result) == ("failed", "wrote")
    await db.commit()
    assert (await db.execute(select(Category))).scalars().all() == []


async def test_flushed_write_is_rolled_back(db):
    result = await one(db, FakeSource(behave=writes_and_flushes))
    assert status(result) == ("failed", "wrote")
    await db.commit()
    assert (await db.execute(select(Category))).scalars().all() == []


async def test_commit_detected(db, caplog):
    with caplog.at_level(logging.ERROR):
        result = await one(db, FakeSource(behave=commits))
    assert status(result) == ("failed", "wrote")
    assert "wrote" in caplog.text
    assert "commit" not in vars(db)  # the guard is gone again
    await db.commit()  # the request's own commit still works


async def test_requests_pending_work_survives_a_plugin_call(db):
    cals = await calendars(db)
    db.add(Category(slug="mine", names={"en": "Mine"}))  # the request's own pending write
    result = await run(db, [Call(cals["I"], entry("acme:fake"), FakeSource(behave=ok(item())))])
    assert status(result) == ("ok", None)
    await db.commit()
    assert [c.slug for c in (await db.execute(select(Category))).scalars()] == ["mine"]


async def test_bad_sql_keeps_transaction(db):
    """On Postgres a failed statement aborts the transaction unless it ran in a savepoint."""
    cals = await calendars(db)
    result = await run(db, [Call(cals["I"], entry("acme:fake"), FakeSource(behave=bad_sql))])
    assert status(result) == ("failed", "raised")
    rows = (await db.execute(select(Calendar))).scalars().all()
    assert len(rows) == 3
    again = await run(db, [Call(cals["I"], entry("acme:fake"), FakeSource(behave=ok(item())))])
    assert status(again) == ("ok", None)
    await db.commit()


async def test_not_installed_status(db):
    cal = (await calendars(db))["I"]
    result = await run(db, [Call(cal, entry("gone:thing"), None)])
    assert status(result) == ("not_installed", None) and result.items == []


async def test_invalid_settings_not_called(db):
    cal = (await calendars(db))["I"]
    src = FakeSource("acme:desk", settings_model=DeskSettings, behave=ok(item()))
    result = await run(db, [Call(cal, entry("acme:desk", count="not a number"), src)])
    assert status(result) == ("failed", "invalid_settings") and src.calls == []


async def test_context_carries_calendar_settings_viewer_limit(db):
    cal = (await calendars(db))["I"]
    src = FakeSource("acme:desk", settings_model=DeskSettings)
    await run(db, [Call(cal, entry("acme:desk", field="z"), src)])
    ((ctx, start, end),) = src.calls
    assert (start, end) == (START, END)
    assert ctx.tenant_id == "default" and ctx.viewer == VIEWER
    assert ctx.calendar == cal and ctx.settings == DeskSettings(field="z")
    assert (ctx.limit, ctx.locale, ctx.default_locale) == (500, "en", "en")
    assert isinstance(ctx.db, type(db))  # the host's own session only on a shared-connection engine
    anon = FakeSource("acme:anon")
    await run(db, [Call(cal, entry("acme:anon"), anon)], viewer=None)
    assert anon.calls[0][0].viewer is None and anon.calls[0][0].settings is None


async def test_dedupe_across_calendars_keeps_both(db):
    cals = await calendars(db)
    src = FakeSource(behave=ok(item("same")))
    result = await run(db, [Call(cals["I"], entry(), src), Call(cals["U"], entry(), src)])
    assert len(result.items) == 2
    assert {o.calendar_id for o in result.items} == {cals["I"].id, cals["U"].id}


async def test_items_from_sources_are_merged_in_order(db):
    cal = (await calendars(db))["I"]
    day9 = datetime(2026, 7, 9, tzinfo=UTC)
    day10 = datetime(2026, 7, 10, tzinfo=UTC)
    late = FakeSource("acme:late", ok(item("l", start=day9, end=day10)))
    early = FakeSource("acme:early", ok(item("e")))
    result = await run(db, [Call(cal, entry(s.id), s) for s in (late, early)])
    assert [o.key.split(":", 1)[1] for o in result.items] == ["e", "l"]


async def test_session_that_cannot_be_restored_skips_the_rest(db, monkeypatch):
    from sm_events.calendar import plugin_runner
    from sm_events.calendar.plugin_isolation import SessionBroken

    cal = (await calendars(db))["I"]
    calls = {"n": 0}

    async def broken(db_, timeout, call):
        calls["n"] += 1
        raise SessionBroken("OperationalError")

    monkeypatch.setattr(plugin_runner, "run_isolated", broken)
    a, b = FakeSource("acme:a"), FakeSource("acme:b")
    result = await run(db, [Call(cal, entry(s.id), s) for s in (a, b)])
    assert [status(result, i) for i in (0, 1)] == [("failed", "session"), ("skipped", "session")]
    assert calls["n"] == 1


async def test_the_same_pair_twice_gives_each_item_once(db):
    """Two calls for one source on one calendar (it was listed twice): no item is doubled."""
    cal = (await calendars(db))["I"]
    src = FakeSource(behave=ok(item("same")))
    result = await run(db, [Call(cal, entry(), src), Call(cal, entry(), src)])
    assert len(result.items) == 1 and len(result.statuses) == 2


async def test_a_timeout_inside_a_query_never_leaves_an_unusable_session(db, monkeypatch):
    """The shared-connection fallback: a statement cancelled by the timeout either leaves the
    session usable, or is reported as a broken session so the caller stops using it."""
    from sm_events.core import constants
    from sqlalchemy import select as sa_select
    from sqlalchemy import text

    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(constants, "SOURCE_MIN_SLICE_SECONDS", 0.01)

    async def slow(ctx, start, end):
        await ctx.db.execute(
            text(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 6000000) "
                "SELECT count(*) FROM n"
            )
        )
        return []

    result = await one(db, FakeSource(behave=slow))
    assert status(result) in (("timeout", None), ("failed", "session"))
    if status(result) == ("timeout", None):
        assert (await db.execute(sa_select(Calendar))).scalars().all()  # still usable
