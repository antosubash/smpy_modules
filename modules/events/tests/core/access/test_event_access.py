"""Event visibility and write rights over the calendar policy's cast."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_events.core.access.events import (
    event_rights,
    is_locked,
    load_event,
    require,
    visible_events,
)
from sm_events.core.errors import Forbidden, NotFound, PublishRequired

from tests.core.access.test_policy import TABLE
from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
SCHEDULED_AT = datetime(2030, 1, 1, tzinfo=UTC)

KINDS = {
    "draft": {"status": "draft"},
    "in_review": {"status": "in_review"},
    "scheduled": {"status": "draft", "publish_at": SCHEDULED_AT},
    "published": {"status": "published"},
}


async def seed(db):
    """``{(calendar letter, kind): event}`` and the calendars."""
    cals = await seed_calendars(db)
    events = {}
    for letter, cal in cals.items():
        for kind, fields in KINDS.items():
            events[letter, kind] = await seed_event(db, cal, title=f"{letter}-{kind}", **fields)
    return cals, events


async def visible(db, who, events, **kw):
    rows = (await db.execute(visible_events(who, **kw))).scalars().all()
    by_id = {e.id: key for key, e in events.items()}
    return {by_id[r.id] for r in rows}


@pytest.mark.parametrize("name", list(TABLE))
async def test_truth_table(db, name):
    uid, perms, view, _edit, _own, write, _publish = TABLE[name]
    who = principal(uid, *perms)
    _cals, events = await seed(db)
    want = {
        (letter, kind)
        for letter in view
        for kind in KINDS
        if kind == "published" or letter in write
    }
    assert await visible(db, who, events) == want, name
    # ``include_unpublished=False`` is published events only, writers included
    only_published = {(letter, "published") for letter in view}
    assert await visible(db, who, events, include_unpublished=False) == only_published, name


@pytest.mark.parametrize("name", list(TABLE))
async def test_nobody_without_write_sees_unpublished(db, name):
    """The leak check, stated on its own: a non-writer never gets a non-published event."""
    uid, perms, _view, _edit, _own, write, _publish = TABLE[name]
    who = principal(uid, *perms)
    _cals, events = await seed(db)
    for letter, kind in await visible(db, who, events):
        assert kind == "published" or letter in write, (name, letter, kind)


async def test_include_unpublished_false_hides_drafts_even_for_writers(db):
    _cals, events = await seed(db)
    got = await visible(db, principal("o", V, P), events, include_unpublished=False)
    assert {kind for _letter, kind in got} == {"published"}


async def test_rights_locked(db):
    cals, events = await seed(db)
    published, draft = events["P", "published"], events["P", "draft"]
    se = principal("se", V)
    rights = await event_rights(db, se, published)
    assert (rights.view, rights.write, rights.publish, rights.locked) == (True, True, False, True)
    with pytest.raises(PublishRequired) as caught:
        require(rights)
    assert caught.value.status_code == 403 and caught.value.code == "publish_required"
    require(await event_rights(db, se, draft))  # an unlocked draft needs only write
    with pytest.raises(PublishRequired):
        require(await event_rights(db, se, draft), publish=True)
    require(await event_rights(db, principal("o", V, P), published))
    assert cals


async def test_scheduled_is_locked(db):
    _cals, events = await seed(db)
    scheduled = events["P", "scheduled"]
    assert is_locked(scheduled) and is_locked(events["P", "published"])
    assert not is_locked(events["P", "draft"]) and not is_locked(events["P", "in_review"])
    with pytest.raises(PublishRequired):
        require(await event_rights(db, principal("se", V), scheduled))
    require(await event_rights(db, principal("o", V, P), scheduled))


async def test_require_distinguishes_404_403(db):
    _cals, events = await seed(db)
    viewer = principal("v", V)
    # a viewer of a public calendar sees the published event but may not write it
    with pytest.raises(Forbidden) as caught:
        require(await event_rights(db, viewer, events["U", "published"]))
    assert caught.value.code == "forbidden"
    # and does not see a draft at all
    with pytest.raises(NotFound):
        require(await event_rights(db, viewer, events["U", "draft"]))


async def test_load_event_invisible_is_404(db):
    _cals, events = await seed(db)
    viewer = principal("v", V)
    with pytest.raises(NotFound):
        await load_event(db, viewer, events["I", "draft"].id)
    with pytest.raises(NotFound):
        await load_event(db, viewer, events["P", "published"].id)  # private calendar
    with pytest.raises(NotFound):
        await load_event(db, viewer, uuid.uuid4())
    got, rights = await load_event(db, viewer, events["I", "published"].id)
    assert got.id == events["I", "published"].id and not rights.write
    got, rights = await load_event(db, principal("o", V), events["I", "draft"].id)
    assert rights.write and not rights.publish


async def test_load_event_trashed(db):
    _cals, events = await seed(db)
    event = events["I", "draft"]
    owner = principal("o", V)
    with pytest.raises(NotFound):
        await load_event(db, owner, event.id, trashed=True)  # not in the trash
    event.is_deleted = True
    event.deleted_at = datetime.now(UTC)
    await db.flush()
    with pytest.raises(NotFound):
        await load_event(db, owner, event.id)
    got, _rights = await load_event(db, owner, event.id, trashed=True)
    assert got.id == event.id
    assert event.id not in {r.id for r in (await db.execute(visible_events(owner))).scalars()}


async def test_trashed_calendar_hides_events(db):
    cals, events = await seed(db)
    cals["I"].is_deleted = True
    cals["I"].deleted_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    for who in (principal("o", V, P), principal("m", M, P), principal("v", V)):
        got = await visible(db, who, events)
        assert not {letter for letter, _kind in got} & {"I"}
    with pytest.raises(NotFound):
        await load_event(db, principal("o", V, P), events["I", "published"].id)
    rights = await event_rights(db, principal("m", M, P), events["I", "published"])
    assert (rights.view, rights.write, rights.publish) == (False, False, False)
