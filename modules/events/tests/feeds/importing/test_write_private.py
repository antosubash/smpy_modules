"""A private item is never written into a published or scheduled event."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_events.core.clock import utcnow
from sm_events.feeds.importing.write import write_item
from sm_events.models import Event, EventText, Revision
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


async def _created(db, imp, **over):
    item = await make_item(db, imp, mapped_event(**over))
    return (await _write(db, imp, item)).event_id


# --- a private item is never written into a published or scheduled event --------------------


async def _existing_event(db, imp, *, publish: bool, scheduled: bool = False):
    event_id = await _created(db, imp, venue_name="Public hall")
    event = await _event(db, event_id)
    event.status, event.published_at = ("published", utcnow()) if publish else ("draft", None)
    if scheduled:
        event.publish_at = datetime(2030, 1, 1, tzinfo=UTC)
    await db.flush()
    return event


async def _private_update(db, imp, event, **over):
    item = await make_item(
        db,
        imp,
        mapped_event(private_class=True, title="Secret plans", venue_name="Hidden room", **over),
        seq=2,
        verdict="update",
        existing=event.id,
        revision=event.revision,
    )
    return await _write(db, imp, item)


async def test_a_private_item_onto_a_draft_updates_and_stays_a_draft(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    draft = await _existing_event(db, imp, publish=False)
    got = await _private_update(db, imp, draft)
    assert got.outcome == "updated"
    await db.refresh(draft)
    assert (draft.status, draft.venue_name) == ("draft", "Hidden room")


async def test_a_private_item_onto_a_published_event_is_skipped_untouched(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    live = await _existing_event(db, imp, publish=True)
    before = (live.revision, live.venue_name, live.status, live.published_at)
    got = await _private_update(db, imp, live)
    assert (got.outcome, got.code, got.event_id) == ("skipped", "private_kept", None)
    await db.refresh(live)
    assert (live.revision, live.venue_name, live.status, live.published_at) == before
    text = (await db.execute(select(EventText).where(EventText.event_id == live.id))).scalar_one()
    assert text.title == "Imported"
    assert len(await _revisions(db, live.id)) == 1


async def test_a_private_item_onto_a_scheduled_event_is_skipped(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    scheduled = await _existing_event(db, imp, publish=False, scheduled=True)
    got = await _private_update(db, imp, scheduled)
    assert (got.outcome, got.code) == ("skipped", "private_kept")
    await db.refresh(scheduled)
    assert scheduled.venue_name == "Public hall" and scheduled.publish_at is not None


async def test_an_item_that_is_no_longer_private_follows_the_normal_rule(db):
    cals = await seed(db)
    imp = await setup(db, cals["P"], publish=True, grants=PUBLISHER)
    live = await _existing_event(db, imp, publish=True)
    item = await make_item(
        db,
        imp,
        mapped_event(title="Now public", venue_name="Open air"),
        seq=2,
        verdict="update",
        existing=live.id,
        revision=live.revision,
    )
    got = await _write(db, imp, item)
    assert got.outcome == "updated"
    await db.refresh(live)
    assert (live.venue_name, live.status) == ("Open air", "published")
