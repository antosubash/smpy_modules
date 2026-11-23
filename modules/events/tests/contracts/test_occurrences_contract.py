"""``sm_events.contracts.occurrences`` and ``mounted``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from sm_events import contracts
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.contracts import occurrences as contract
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Visibility

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event
from tests.support.occurrences import OWNER, read, utc

START, END = utc(2026, 6, 1), utc(2026, 8, 1)


async def test_anonymous_gets_public_published_only(db):
    cals = await seed_calendars(db)
    for letter, cal in cals.items():
        await seed_event(db, cal, title=f"{letter}-draft", status="draft")
        await seed_event(db, cal, title=f"{letter}-pub", status="published")
    page = await contract.occurrences(db, tenant_id="default", viewer=None, start=START, end=END)
    assert [o.title for o in page.items] == ["U-pub"]
    assert {o.event_status for o in page.items} == {"published"}


async def test_viewer_matches_internal_read(db):
    cals = await seed_calendars(db)
    for letter, cal in cals.items():
        await seed_event(db, cal, title=f"{letter}-draft", status="draft")
        await seed_event(db, cal, title=f"{letter}-pub", status="published")
    for who in (OWNER, principal("se", "events.view"), principal("v", "events.view")):
        got = await contract.occurrences(db, tenant_id="default", viewer=who, start=START, end=END)
        want = await read(db, who, START, END, OccurrenceFilters())
        assert got.items == want.items
        assert got.truncated == want.truncated


async def test_filters_pass_through(db):
    cals = await seed_calendars(db)
    for letter, cal in cals.items():
        await seed_event(db, cal, title=letter, status="published")
    page = await contract.occurrences(
        db,
        tenant_id="default",
        viewer=OWNER,
        start=START,
        end=END,
        calendar_ids=[cals["U"].id],
    )
    assert [o.title for o in page.items] == ["U"]


@pytest.mark.unbound_tenant
async def test_contract_binds_tenant(db):
    with tenant_scope("a"):
        cal = Calendar(slug="a", name="a", owner_id="o", visibility=Visibility.PUBLIC)
        db.add(cal)
        await db.flush()
        await seed_event(db, cal, title="a-event", status="published")
    with tenant_scope("b"):
        cal = Calendar(slug="b", name="b", owner_id="o", visibility=Visibility.PUBLIC)
        db.add(cal)
        await db.flush()
        await seed_event(db, cal, title="b-event", status="published")
    got = await contract.occurrences(db, tenant_id="b", viewer=None, start=START, end=END)
    assert [o.title for o in got.items] == ["b-event"]
    with pytest.raises(ValueError):
        await contract.occurrences(db, tenant_id="a\n", viewer=None, start=START, end=END)


def test_mounted():
    from sm_events.core.services import EventsServices

    bare = FastAPI()
    assert contracts.mounted(bare) is False
    bare.state.sm_events = EventsServices(settings=None)
    assert contracts.mounted(bare) is True


def test_contract_surface():
    assert contract.__all__ == ["Occurrence", "OccurrencePage", "occurrences"]


@pytest.mark.parametrize(
    "start, end",
    [
        (utc(2026, 6, 1), datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=5)))),
        (datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5))), utc(2026, 6, 1)),
        (utc(9000, 1, 1), utc(9000, 1, 2)),
        (utc(1899, 12, 31), utc(1900, 1, 2)),
    ],
)
async def test_an_instant_outside_a_sane_range_is_a_value_error_before_any_query(db, start, end):
    with pytest.raises(ValueError, match="supported years"):
        await contract.occurrences(db, tenant_id="default", viewer=OWNER, start=start, end=end)


async def test_contract_without_viewer_skips_plugins(db, monkeypatch):
    from sm_events.calendar.plugins import registry
    from sm_events.calendar.plugins.extension_types import SourceViewer

    from tests.support.sources import FakeSource, install, item, ok

    fake = FakeSource("acme:fake", ok(item("a")), public=True)
    install(monkeypatch, fake)
    try:
        cals = await seed_calendars(db)
        cals["U"].sources = [{"id": "acme:fake", "settings": {}}]
        await db.flush()
        # Anonymous: a public source is called, with no viewer.
        page = await contract.occurrences(
            db, tenant_id="default", viewer=None, start=START, end=END
        )
        assert [o.source for o in page.items] == ["acme:fake"]
        assert fake.calls[0][0].viewer is None
        fake.calls.clear()
        # Signed in without a source_viewer: every plugin pair is skipped, fail safe.
        page = await contract.occurrences(
            db, tenant_id="default", viewer=OWNER, start=START, end=END
        )
        assert page.items == [] and fake.calls == []
        assert [(s.status, s.code) for s in page.sources] == [("skipped", "no_viewer")]
        # With one, the source runs for them.
        who = SourceViewer(user_id="o", roles=(), permissions=frozenset({"events.view"}))
        page = await contract.occurrences(
            db, tenant_id="default", viewer=OWNER, start=START, end=END, source_viewer=who
        )
        assert [o.source for o in page.items] == ["acme:fake"]
        assert fake.calls[0][0].viewer == who
        only = await contract.occurrences(
            db, tenant_id="default", viewer=None, start=START, end=END, sources=["events"]
        )
        assert only.items == [] and len(fake.calls) == 1  # the built-in only: no plugin call
    finally:
        registry.reset_registry()
