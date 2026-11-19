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
    Revision,
)
from sqlalchemy import select

from tests.feeds.importing.staging_support import seed
from tests.feeds.importing.write_support import make_item, mapped_event, setup

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
