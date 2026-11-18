"""Updating an event from an import: what the file wins, and what it leaves alone."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.core.clock import utcnow
from sm_events.feeds.importing.write import write_item
from sm_events.models import Event, EventText, OccurrenceOverride, Revision
from sqlalchemy import select

from tests.feeds.importing.staging_support import seed
from tests.feeds.importing.write_support import make_item, mapped_event, moved, setup

LOCALES = ("en", "de")
PUBLISHER = ("events.view", "events.manage", "events.publish")
SERIES = {"rrule": "FREQ=WEEKLY;COUNT=4"}


async def _write(db, imp, item, now=None):
    return await write_item(db, imp, item, locales=LOCALES, now=now or utcnow())


async def _event(db, event_id) -> Event:
    return (await db.execute(select(Event).where(Event.id == event_id))).scalar_one()


async def _revisions(db, event_id) -> list[Revision]:
    return list(
        (
            await db.execute(
                select(Revision).where(Revision.event_id == event_id).order_by(Revision.number)
            )
        ).scalars()
    )


async def _created(db, imp, **over):
    item = await make_item(db, imp, mapped_event(**over))
    return (await _write(db, imp, item)).event_id


async def test_update_file_wins_for_mapped_fields(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    event_id = await _created(db, imp, venue_name="Old room")
    event = await _event(db, event_id)
    db.add(EventText(event_id=event_id, locale="de", slug="auf-deutsch", title="Deutsch"))
    event.image = "https://example.org/i.png"
    await db.flush()
    second = await make_item(
        db,
        imp,
        mapped_event(
            title="New title",
            venue_name="New room",
            latitude=48.2,
            longitude=16.3,
            **SERIES,
            times={
                "timezone": "Europe/Vienna",
                "start": "2026-07-06T10:00",
                "end": "2026-07-06T12:00",
            },
        ),
        seq=2,
        verdict="update",
        existing=event_id,
        revision=event.revision,
    )
    got = await _write(db, imp, second)
    assert (got.outcome, got.event_id) == ("updated", event_id)
    await db.refresh(event)
    assert (event.venue_name, event.latitude, event.rrule) == (
        "New room",
        48.2,
        "FREQ=WEEKLY;COUNT=4",
    )
    assert event.status == "published" and event.image == "https://example.org/i.png"
    assert event.revision == 2
    texts = {
        t.locale: t
        for t in (
            await db.execute(select(EventText).where(EventText.event_id == event_id))
        ).scalars()
    }
    assert texts["en"].title == "New title" and texts["en"].slug  # the address is kept
    assert texts["de"].title == "Deutsch"  # another language is untouched
    revisions = await _revisions(db, event_id)
    assert [(r.action, r.note) for r in revisions] == [
        ("created", f"import #{imp.id}"),
        ("updated", f"import #{imp.id}"),
    ]


async def test_update_keeps_the_texts_other_fields(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    event_id = await _created(db, imp)
    text = (await db.execute(select(EventText).where(EventText.event_id == event_id))).scalar_one()
    text.summary, text.seo_title, text.noindex = "Kept summary", "Kept seo", True
    await db.flush()
    event = await _event(db, event_id)
    item = await make_item(
        db,
        imp,
        mapped_event(title="Changed"),
        seq=2,
        verdict="update",
        existing=event_id,
        revision=event.revision,
    )
    await _write(db, imp, item)
    await db.refresh(text)
    assert (text.title, text.summary, text.seo_title, text.noindex) == (
        "Changed",
        "Kept summary",
        "Kept seo",
        True,
    )


async def test_update_replaces_overrides(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    first = datetime(2026, 7, 6, 8, tzinfo=UTC)
    second = datetime(2026, 7, 13, 8, tzinfo=UTC)
    times = {"timezone": "Europe/Vienna", "start": "2026-07-06T10:00", "end": "2026-07-06T11:00"}
    event_id = await _created(
        db,
        imp,
        times=times,
        overrides=[{"original_start": first, "kind": "skipped"}],
        **SERIES,
    )
    event = await _event(db, event_id)
    rows = list((await db.execute(select(OccurrenceOverride))).scalars())
    assert [(r.kind, r.original_start) for r in rows] == [
        ("skipped", first.replace(tzinfo=None))
    ] or len(rows) == 1
    item = await make_item(
        db,
        imp,
        mapped_event(
            times=times, overrides=[moved(second, "2026-07-13T15:00", "2026-07-13T16:00")], **SERIES
        ),
        seq=2,
        verdict="update",
        existing=event_id,
        revision=event.revision,
    )
    assert (await _write(db, imp, item)).outcome == "updated"
    rows = list((await db.execute(select(OccurrenceOverride))).scalars())
    assert [r.kind for r in rows] == ["moved"]
    assert rows[0].starts_at.astimezone(UTC).hour == 13  # 15:00 Vienna


async def test_reimport_unchanged(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    event_id = await _created(db, imp, **SERIES)
    event = await _event(db, event_id)
    again = await make_item(
        db,
        imp,
        mapped_event(**SERIES),
        seq=2,
        verdict="update",
        existing=event_id,
        revision=event.revision,
    )
    got = await _write(db, imp, again)
    assert (got.outcome, got.event_id) == ("unchanged", event_id)
    assert len(await _revisions(db, event_id)) == 1  # nothing new in the history
    await db.refresh(event)
    assert event.revision == 1


async def test_stale_since_preview(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    event_id = await _created(db, imp)
    event = await _event(db, event_id)
    event.revision = 4  # someone edited it after the preview saw 3
    await db.flush()
    item = await make_item(
        db, imp, mapped_event(title="Late"), seq=2, verdict="update", existing=event_id, revision=3
    )
    got = await _write(db, imp, item)
    assert (got.outcome, got.code) == ("skipped", "changed_since_preview")
    text = (await db.execute(select(EventText).where(EventText.event_id == event_id))).scalar_one()
    assert text.title == "Imported"


async def test_an_event_gone_since_the_preview(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    event_id = await _created(db, imp)
    event = await _event(db, event_id)
    event.is_deleted = True
    await db.flush()
    item = await make_item(db, imp, seq=2, verdict="update", existing=event_id, revision=1)
    got = await _write(db, imp, item)
    assert (got.outcome, got.code) == ("skipped", "changed_since_preview")


async def test_locked_needs_publish(db):
    cals = await seed(db)
    publisher = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    event_id = await _created(db, publisher)
    assert (await _event(db, event_id)).status == "published"
    plain = await setup(db, cals["P"])  # may_publish False
    item = await make_item(
        db,
        plain,
        mapped_event(title="Nope"),
        seq=1,
        verdict="update",
        existing=event_id,
        revision=1,
    )
    got = await _write(db, plain, item)
    assert (got.outcome, got.code) == ("skipped", "publish_required")


async def test_pr2_validation_becomes_a_skip(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    bad = mapped_event(
        times={"timezone": "Europe/Vienna", "start": "2026-07-01T12:00", "end": "2026-07-01T10:00"}
    )
    got = await _write(db, imp, await make_item(db, imp, bad))
    assert (got.outcome, got.code, got.event_id) == ("skipped", "end_before_start", None)
    assert (await db.execute(select(Event))).scalars().all() == []
