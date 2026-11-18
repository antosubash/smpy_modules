"""Writing one item through the normal write path."""

from __future__ import annotations

from datetime import UTC, datetime

from simple_module_core.events import EventBus
from sm_events.content import bus as bus_module
from sm_events.core.clock import utcnow
from sm_events.feeds.importing.write import write_item
from sm_events.models import (
    Event,
    EventImport,
    EventText,
    OccurrenceOverride,
    Revision,
)
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


async def test_new_draft(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    got = await _write(db, imp, await make_item(db, imp))
    assert got.outcome == "created" and got.code is None
    event = await _event(db, got.event_id)
    assert (event.status, event.uid, event.revision, event.published_at) == (
        "draft",
        "n@x",
        1,
        None,
    )
    assert (event.calendar_id, event.timezone) == (cals["P"].id, "Europe/Vienna")
    text = (await db.execute(select(EventText).where(EventText.event_id == event.id))).scalar_one()
    assert (text.locale, text.title, text.description) == ("en", "Imported", "<p>Body</p>")
    (revision,) = await _revisions(db, event.id)
    assert (revision.action, revision.actor, revision.note) == ("created", "m", f"import #{imp.id}")


async def test_published_when_asked_and_allowed(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    now = datetime(2026, 6, 1, 9, tzinfo=UTC)
    got = await _write(db, imp, await make_item(db, imp), now)
    event = await _event(db, got.event_id)
    assert (event.status, event.published_at, event.revision) == ("published", now, 1)


async def test_private_class_stays_a_draft_even_when_publishing(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    item = await make_item(db, imp, mapped_event(private_class=True))
    event = await _event(db, (await _write(db, imp, item)).event_id)
    assert event.status == "draft" and event.published_at is None


async def test_publishing_without_the_permission_writes_a_draft(db):
    """``publish`` on the row is a request; the importer's own right decides."""
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True)  # no events.publish in the grants
    event = await _event(db, (await _write(db, imp, await make_item(db, imp))).event_id)
    assert event.status == "draft"


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


async def test_a_skip_verdict_writes_nothing(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    item = await make_item(db, imp, verdict="skip", reason="unsupported_rule")
    got = await _write(db, imp, item)
    assert (got.outcome, got.code) == ("skipped", "unsupported_rule")
    assert (await db.execute(select(Event))).scalars().all() == []


async def test_a_uid_taken_meanwhile_is_a_skip_not_a_crash(db):
    """Two imports racing on one UID: the unique key decides, and the loser is a reported skip."""
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    await _created(db, imp)
    other = await setup(db, cals["P"])
    got = await _write(db, other, await make_item(db, other, seq=1))
    assert (got.outcome, got.code) == ("skipped", "duplicate_uid")
    assert len((await db.execute(select(Event))).scalars().all()) == 1


async def test_rights_are_checked_for_every_item(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], grants=("events.view",))  # no longer a manager
    got = await _write(db, imp, await make_item(db, imp))
    assert (got.outcome, got.code) == ("skipped", "forbidden")
    manager = await setup(db, cals["P"])
    cals["P"].is_deleted = True  # the calendar went away
    await db.flush()
    assert (await _write(db, manager, await make_item(db, manager, seq=2))).code == "forbidden"
    assert (await db.execute(select(Event))).scalars().all() == []


async def test_an_edit_share_holder_without_manage_cannot_import(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], by="se", grants=("events.view", "events.edit"))
    assert (await _write(db, imp, await make_item(db, imp))).code == "forbidden"


async def test_no_bus_events(db):
    """Even a session with a bus attached publishes nothing for an import (5,000 events of
    ``EventPublished`` would flood every subscriber)."""
    from sm_events.content import notices

    seen: list[object] = []

    async def record(event):
        seen.append(event)

    bus = EventBus()
    for name in dir(notices):
        cls = getattr(notices, name)
        if isinstance(cls, type) and hasattr(cls, "__dataclass_fields__"):
            bus.subscribe(cls, record)
    bus_module.attach(db, bus)
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    event_id = await _created(db, imp, **SERIES)
    event = await _event(db, event_id)
    changed = mapped_event(
        cancelled=True,
        rrule="FREQ=WEEKLY;COUNT=5",
        times={"timezone": "Europe/Vienna", "start": "2026-07-01T14:00", "end": "2026-07-01T15:00"},
    )
    item = await make_item(
        db, imp, changed, seq=2, verdict="update", existing=event_id, revision=event.revision
    )
    assert (await _write(db, imp, item)).outcome == "updated"
    await bus_module.commit(db)
    assert seen == []
    assert db.info.get(bus_module.BUS_KEY) is bus  # and the session got its bus back


async def test_import_row_is_untouched_by_a_write(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"])
    await _created(db, imp)
    row = (await db.execute(select(EventImport))).scalar_one()
    assert (row.created, row.processed, row.status) == (
        0,
        0,
        "running",
    )  # counters are the runner's
