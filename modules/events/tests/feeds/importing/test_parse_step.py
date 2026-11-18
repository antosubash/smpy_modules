"""The parse step: verdicts, staged items, failures, all-or-nothing."""

from __future__ import annotations

import json

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.importing import staging
from sm_events.feeds.importing.fence import claim
from sm_events.models import EventImport, EventImportItem
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.staging_support import make_import, seed
from tests.support.calendars import seed_event

LOCALES = ("en",)


async def test_parse_verdicts(db):
    cals = await seed(db)
    await seed_event(db, cals["P"], uid="old@x", status="published", revision=3)
    await seed_event(db, cals["P"], uid="gone@x", is_deleted=True)
    await seed_event(db, cals["I"], uid="other@x")
    data = corpus.calendar(
        *corpus.vevent("new@x"),
        *corpus.vevent("old@x"),
        *corpus.vevent("gone@x"),
        *corpus.vevent("other@x"),
        *corpus.vevent("bad@x", "RRULE:FREQ=SECONDLY"),
    )
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "staged"
    items = {
        i.uid: i
        for i in (await db.execute(select(EventImportItem).order_by(EventImportItem.seq))).scalars()
    }
    got = {uid: (i.verdict, i.reason) for uid, i in items.items()}
    assert got == {
        "new@x": ("new", None),
        "old@x": ("update", None),
        "gone@x": ("skip", "uid_in_trash"),
        "other@x": ("new", None),
        "bad@x": ("skip", "unsupported_rule"),
    }
    assert items["old@x"].expected_revision == 3 and items["old@x"].existing_event_id is not None
    assert [i.seq for i in items.values()] == [1, 2, 3, 4, 5]
    await db.refresh(imp)
    assert (imp.status, imp.source, imp.total) == ("staged", None, 5)
    assert imp.counts == {"new": 2, "update": 1, "unchanged": 0, "skip": 2}
    assert imp.reasons["uid_in_trash"] == 1 and imp.reasons["unsupported_rule"] == 1
    assert (imp.lease_owner, imp.lease_until) == (None, None)


async def test_parse_payload_is_the_mapped_event_and_holds_no_personal_data(db):
    cals = await seed(db)
    data = corpus.calendar(
        *corpus.vevent(
            "p@x",
            "ATTENDEE;CN=Jane Doe:mailto:jane@example.com",
            "ORGANIZER:mailto:boss@example.com",
            "BEGIN:VALARM",
            "ATTACH:http://127.0.0.1/x",
            "END:VALARM",
        )
    )
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    item = (await db.execute(select(EventImportItem))).scalar_one()
    await db.refresh(imp)
    blob = json.dumps([item.payload, item.notes, item.title, imp.counts, imp.reasons, imp.dropped])
    for private in ("jane", "Jane", "boss", "example.com", "127.0.0.1"):
        assert private not in blob
    assert imp.dropped == {"ATTENDEE": 1, "ORGANIZER": 1, "VALARM": 1}
    assert item.payload["uid"] == "p@x" and item.payload["times"]["timezone"] == "UTC"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (corpus.invalid_utf8(), "ics_encoding"),
        (corpus.depth(4), "too_deep"),
        (corpus.events(constants.IMPORT_MAX_EVENTS + 1), "too_many_events"),
    ],
)
async def test_parse_failure_records_code(db, data, code):
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "failed"
    await db.refresh(imp)
    assert (imp.status, imp.error_code, imp.source) == ("failed", code, None)
    assert (await db.execute(select(EventImportItem))).scalars().all() == []
    assert imp.finished_at is not None and imp.lease_owner is None


async def test_parse_is_all_or_nothing(db, monkeypatch):
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=corpus.simple(5))
    await db.commit()
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await db.commit()
    monkeypatch.setattr(constants, "IMPORT_ITEM_CHUNK", 2)
    real = db.flush
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return await real(*a, **k)

    monkeypatch.setattr(db, "flush", flaky)
    with pytest.raises(RuntimeError):
        await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    monkeypatch.undo()
    await db.rollback()
    row = (await db.execute(select(EventImport))).scalar_one()
    assert row.status == "parsing" and row.source == corpus.simple(5)  # left for the janitor
    assert (await db.execute(select(EventImportItem))).scalars().all() == []


async def test_no_library_parser_runs(db, monkeypatch):
    import icalendar

    def refuse(*_a, **_k):
        raise AssertionError("an upload must never reach the iCalendar library")

    monkeypatch.setattr(icalendar.Calendar, "from_ical", refuse)
    cals = await seed(db)
    imp = await make_import(db, cals["P"], data=corpus.simple(2))
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "staged"


async def test_a_trashed_calendar_fails_the_import(db):
    cals = await seed(db)
    imp = await make_import(db, cals["P"])
    cals["P"].is_deleted = True
    await db.flush()
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    assert await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES) == "failed"
    await db.refresh(imp)
    assert (imp.error_code, imp.source) == ("import_failed", None)


async def test_categories_match_by_default_locale_name(db):
    from sm_events.models import Category

    cals = await seed(db)
    cat = Category(slug="talks", names={"en": "Talks", "de": "Vortraege"})
    db.add(cat)
    await db.flush()
    imp = await make_import(
        db, cals["P"], data=corpus.calendar(*corpus.vevent("c@x", "CATEGORIES:talks"))
    )
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    item = (await db.execute(select(EventImportItem))).scalar_one()
    assert item.payload["category_id"] == str(cat.id)


async def test_the_preview_shows_the_verdict_the_write_produces_for_private_items(db):
    """A private item onto a published or scheduled event is previewed as a skip
    (``private_kept``); onto a draft, or a public item onto a published one, as an update."""
    cals = await seed(db)
    await seed_event(db, cals["P"], uid="live@x", status="published")
    await seed_event(db, cals["P"], uid="sched@x", publish_at=utcnow())
    await seed_event(db, cals["P"], uid="draft@x", status="draft")
    data = corpus.calendar(
        *corpus.vevent("live@x", "CLASS:PRIVATE"),
        *corpus.vevent("sched@x", "CLASS:CONFIDENTIAL"),
        *corpus.vevent("draft@x", "CLASS:PRIVATE"),
        *corpus.vevent("fresh@x", "CLASS:PRIVATE"),
    )
    other = corpus.calendar(*corpus.vevent("live@x"))
    imp = await make_import(db, cals["P"], data=data)
    await claim(db, tenant_id="default", import_id=imp.id, owner="w", now=utcnow())
    await staging.parse_step(db, imp, owner="w", now=utcnow(), locales=LOCALES)
    got = {
        i.uid: (i.verdict, i.reason) for i in (await db.execute(select(EventImportItem))).scalars()
    }
    assert got == {
        "live@x": ("skip", "private_kept"),
        "sched@x": ("skip", "private_kept"),
        "draft@x": ("update", None),
        "fresh@x": ("new", None),
    }
    again = await make_import(db, cals["P"], data=other)
    await claim(db, tenant_id="default", import_id=again.id, owner="w2", now=utcnow())
    await staging.parse_step(db, again, owner="w2", now=utcnow(), locales=LOCALES)
    item = (
        await db.execute(select(EventImportItem).where(EventImportItem.import_id == again.id))
    ).scalar_one()
    assert (item.verdict, item.reason) == ("update", None)
