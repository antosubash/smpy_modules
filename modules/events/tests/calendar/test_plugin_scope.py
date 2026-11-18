"""Which plugin pairs a read calls: visibility, anonymity, the viewer, the filter."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry
from sm_events.calendar.extension_types import SourceViewer
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.plugin_scope import plugin_calls
from sm_events.core.access.public import ANONYMOUS

from tests.support.access import principal, seed_calendars
from tests.support.sources import FakeSource, install

SV = SourceViewer(user_id="o", roles=(), permissions=frozenset({"events.view"}))
OWNER = principal("o", "events.view")
VIEWER = principal("v", "events.view")


@pytest.fixture
def plugins(monkeypatch):
    pub, priv = FakeSource("acme:pub", public=True), FakeSource("acme:priv", public=False)
    install(monkeypatch, pub, priv)
    yield pub, priv
    registry.reset_registry()


async def enable(db, **by_letter):
    cals = await seed_calendars(db)
    for letter, ids in by_letter.items():
        cals[letter].sources = [{"id": i, "settings": {}} for i in ids]
    await db.flush()
    return cals


def pairs(calls):
    return [(c.calendar.slug, c.entry.id) for c in calls]


async def test_only_visible_calendars(db, plugins):
    await enable(db, P=["acme:pub"], I=["acme:pub"])
    calls, skipped = await plugin_calls(db, VIEWER, SV, OccurrenceFilters())
    assert pairs(calls) == [("internal", "acme:pub")]  # P is private: not V's
    assert skipped == []
    calls, _ = await plugin_calls(db, OWNER, SV, OccurrenceFilters())
    assert pairs(calls) == [("internal", "acme:pub"), ("private", "acme:pub")]  # by name


async def test_anonymous_public_sources_on_public_calendars_only(db, plugins):
    await enable(
        db, P=["acme:pub"], I=["acme:pub", "acme:priv"], U=["acme:pub", "acme:priv", "gone:x"]
    )
    calls, skipped = await plugin_calls(db, ANONYMOUS, None, OccurrenceFilters())
    assert pairs(calls) == [("public", "acme:pub")]
    assert skipped == []


async def test_anonymous_ignores_a_source_viewer(db, plugins):
    await enable(db, U=["acme:pub"])
    calls, _ = await plugin_calls(db, ANONYMOUS, SV, OccurrenceFilters())
    assert pairs(calls) == [("public", "acme:pub")]


async def test_signed_in_without_viewer_skipped(db, plugins):
    cals = await enable(db, I=["acme:priv", "acme:pub", "gone:x"])
    calls, skipped = await plugin_calls(db, OWNER, None, OccurrenceFilters())
    assert pairs(calls) == [("internal", "gone:x")]  # not installed: still reported, by the runner
    assert calls[0].source is None
    assert [(s.id, s.calendar_id, s.status, s.code) for s in skipped] == [
        ("acme:priv", cals["I"].id, "skipped", "no_viewer"),
        ("acme:pub", cals["I"].id, "skipped", "no_viewer"),
    ]


async def test_signed_in_sees_private_sources_and_missing_ones(db, plugins):
    await enable(db, I=["gone:x", "acme:priv"])
    calls, _ = await plugin_calls(db, OWNER, SV, OccurrenceFilters())
    assert pairs(calls) == [("internal", "acme:priv"), ("internal", "gone:x")]


async def test_sources_filter(db, plugins):
    await enable(db, I=["acme:pub", "acme:priv"])
    only = OccurrenceFilters(sources=frozenset({"acme:priv"}))
    assert pairs((await plugin_calls(db, OWNER, SV, only))[0]) == [("internal", "acme:priv")]
    builtin_only = OccurrenceFilters(sources=frozenset({"events"}))
    assert await plugin_calls(db, OWNER, SV, builtin_only) == ([], [])
    mixed = OccurrenceFilters(sources=frozenset({"events", "acme:pub"}))
    assert pairs((await plugin_calls(db, OWNER, SV, mixed))[0]) == [("internal", "acme:pub")]


async def test_invisible_calendar_in_filter_dropped_silently(db, plugins):
    cals = await enable(db, P=["acme:pub"], I=["acme:pub"])
    only_private = OccurrenceFilters(calendar_ids=frozenset({cals["P"].id}))
    assert await plugin_calls(db, VIEWER, SV, only_private) == ([], [])
    both = OccurrenceFilters(calendar_ids=frozenset({cals["P"].id, cals["I"].id}))
    assert pairs((await plugin_calls(db, VIEWER, SV, both))[0]) == [("internal", "acme:pub")]


async def test_malformed_entries_are_ignored(db, plugins):
    cals = await seed_calendars(db)
    cals["I"].sources = [1, None, {"id": "acme:pub", "settings": {}}, {"nope": 1}]
    await db.flush()
    calls, _ = await plugin_calls(db, OWNER, SV, OccurrenceFilters())
    assert pairs(calls) == [("internal", "acme:pub")]


async def test_a_category_filter_excludes_every_plugin_source(db, plugins):
    import uuid

    await enable(db, I=["acme:pub", "acme:priv"])
    filtered = OccurrenceFilters(category_ids=frozenset({uuid.uuid4()}))
    assert await plugin_calls(db, OWNER, SV, filtered) == ([], [])
    assert await plugin_calls(db, ANONYMOUS, None, filtered) == ([], [])
