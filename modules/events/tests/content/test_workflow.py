"""The review and publishing workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.content import bus
from sm_events.content.workflow import TRANSITIONS, transition
from sm_events.contracts import events as contract
from sm_events.core.access.events import is_locked
from sm_events.core.errors import (
    Forbidden,
    InvalidTimes,
    InvalidTransition,
    NotFound,
    PublishRequired,
    Stale,
)
from sm_events.models import Calendar, Revision
from sqlalchemy import select

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event
from tests.support.writes import OWNER, OWNER_P, SE, VIEWER, make, recording, revision_count

NOW = datetime(2026, 7, 1, 12, tzinfo=UTC)
FUTURE = NOW + timedelta(days=30)

# (status, scheduled?) cells that can exist; "published and scheduled" cannot.
CELLS = [
    ("draft", False),
    ("draft", True),
    ("in_review", False),
    ("in_review", True),
    ("published", False),
]
# (action, status, scheduled) -> the status afterwards, and whether publish_at is set afterwards.
ALLOWED = {
    ("submit", "draft", False): ("in_review", False),
    ("withdraw", "in_review", False): ("draft", False),
    ("approve", "draft", False): ("published", False),
    ("approve", "in_review", False): ("published", False),
    ("reject", "in_review", False): ("draft", False),
    ("unschedule", "draft", True): ("draft", False),
    ("unschedule", "in_review", True): ("in_review", False),
    ("unpublish", "published", False): ("draft", False),
}


SLUGS = {"P": "private", "I": "internal", "U": "public"}


async def calendar(db, letter):
    """The access cast's calendar ``letter``, seeded on first use."""
    found = (
        await db.execute(select(Calendar).where(Calendar.slug == SLUGS[letter]))
    ).scalar_one_or_none()
    return found or (await seed_calendars(db))[letter]


async def seeded(db, status="draft", scheduled=False, letter="I", **fields):
    cal = await calendar(db, letter)
    if scheduled:
        fields["publish_at"] = FUTURE
    if status == "published":
        fields["published_at"] = NOW - timedelta(days=1)
    return await seed_event(db, cal, status=status, **fields)


async def run(db, who, event, action, **kw):
    kw.setdefault("expected", event.revision)
    if action == "reject":
        kw.setdefault("note", "needs work")
    return await transition(db, who, event.id, action, now=NOW, **kw)


def test_table_matches_ruling():
    assert set(TRANSITIONS) == {
        "submit",
        "withdraw",
        "approve",
        "reject",
        "unschedule",
        "unpublish",
    }
    assert {a for a, (_s, needs) in TRANSITIONS.items() if needs} == {
        "approve", "reject", "unschedule", "unpublish",
    }  # fmt: skip


@pytest.mark.parametrize("action", sorted(TRANSITIONS))
@pytest.mark.parametrize(("status", "scheduled"), CELLS)
async def test_transition_table(db, action, status, scheduled):
    event = await seeded(db, status, scheduled)
    before = await revision_count(db, event.id)
    cell = (action, status, scheduled)
    if cell not in ALLOWED:
        with pytest.raises(InvalidTransition) as raised:
            await run(db, OWNER_P, event, action)
        assert raised.value.code == "invalid_transition"
        await db.refresh(event)
        assert event.revision == 1 and event.status == status
        assert await revision_count(db, event.id) == before
        return
    got = await run(db, OWNER_P, event, action)
    after_status, scheduled_after = ALLOWED[cell]
    assert got.status == after_status and (got.publish_at is not None) is scheduled_after
    assert got.revision == 2 and await revision_count(db, event.id) == before + 1


async def test_submit_by_writer_without_publish(db):
    event = await seeded(db)
    got = await run(db, OWNER, event, "submit")
    assert got.status == "in_review"
    back = await run(db, OWNER, got, "withdraw")
    assert back.status == "draft"


async def test_approve_needs_publish(db):
    event = await seeded(db, "in_review")
    for action in ("approve", "reject", "unschedule", "unpublish"):
        with pytest.raises(PublishRequired):
            await run(db, OWNER, event, action, **({"note": "x"} if action == "reject" else {}))
    assert event.revision == 1 and await revision_count(db, event.id) == 0


async def test_approve_future_schedules(db):
    event = await seeded(db, "in_review")
    rec = recording(db)
    got = await run(db, OWNER_P, event, "approve", publish_at_local="2026-08-01T10:00")
    assert got.status == "in_review" and got.published_at is None
    assert got.publish_at == datetime(2026, 8, 1, 10, tzinfo=UTC)  # the seed zone is UTC
    assert is_locked(got)
    (last,) = (await db.execute(select(Revision).where(Revision.event_id == event.id))).scalars()
    assert last.action == "scheduled" and last.number == 2
    await bus.commit(db)
    assert rec.seen == []


async def test_approve_past_publishes_now(db):
    event = await seeded(db)
    rec = recording(db)
    got = await run(db, OWNER_P, event, "approve", publish_at_local="2026-06-01T10:00")
    assert got.status == "published" and got.published_at == NOW and got.publish_at is None
    await bus.commit(db)
    (seen,) = rec.seen
    assert isinstance(seen, contract.EventPublished) and seen.published_at == NOW
    assert seen.event_id == event.id and seen.tenant_id == "default"


async def test_approve_without_time_publishes_now(db):
    event = await seeded(db)
    got = await run(db, OWNER_P, event, "approve")
    assert got.status == "published" and got.published_at == NOW


async def test_approve_local_publish_at(db):
    event = await seeded(db, timezone="Europe/Vienna")
    got = await run(db, OWNER_P, event, "approve", publish_at_local="2026-07-20T10:00")
    assert got.publish_at == datetime(2026, 7, 20, 8, tzinfo=UTC)  # CEST: 10:00 local is 08:00Z
    assert got.status == "draft"
    winter = await seeded(db, timezone="Europe/Vienna")
    got = await run(db, OWNER_P, winter, "approve", publish_at_local="2026-12-20T10:00")
    assert got.publish_at == datetime(2026, 12, 20, 9, tzinfo=UTC)


async def test_approve_local_time_in_a_gap_or_malformed_is_refused(db):
    event = await seeded(db, timezone="Europe/Vienna")
    for local in ("2027-03-28T02:30", "tomorrow", "2026-08-01T10:00+02:00", "2026-08-01"):
        with pytest.raises(InvalidTimes) as raised:
            await run(db, OWNER_P, event, "approve", publish_at_local=local)
        assert raised.value.code == "invalid_local_time"
        await db.refresh(event)
    assert event.revision == 1


async def test_reject_note_required_and_recorded(db):
    event = await seeded(db, "in_review")
    got = await run(db, OWNER_P, event, "reject", note="too vague")
    assert got.status == "draft"
    last = (
        await db.execute(
            select(Revision).where(Revision.event_id == event.id, Revision.number == 2)
        )
    ).scalar_one()
    assert (last.action, last.note) == ("rejected", "too vague")
    from sm_events.web.schemas.workflow import RejectIn

    for bad in ("", "   ", "x" * 1001):
        with pytest.raises(ValueError):
            RejectIn(expected_revision=1, note=bad)


async def test_unpublish_keeps_published_at(db):
    event = await seeded(db, "published")
    stamp = event.published_at
    rec = recording(db)
    got = await run(db, OWNER_P, event, "unpublish")
    assert got.status == "draft" and got.published_at == stamp
    await bus.commit(db)
    assert rec.seen == []


async def test_unschedule(db):
    event = await seeded(db, scheduled=True)
    got = await run(db, OWNER_P, event, "unschedule")
    assert got.publish_at is None and got.status == "draft" and not is_locked(got)


async def test_scheduled_event_is_locked_for_a_writer(db):
    event = await seeded(db, scheduled=True, letter="P")
    with pytest.raises(PublishRequired):
        await run(db, SE, event, "submit")
    assert event.revision == 1


async def test_stale_transition(db):
    event = await seeded(db)
    with pytest.raises(Stale) as raised:
        await run(db, OWNER_P, event, "approve", expected=3)
    assert raised.value.current_revision == 1
    await db.refresh(event)
    assert event.status == "draft" and await revision_count(db, event.id) == 0


async def test_stale_beats_invalid_state(db):
    event = await seeded(db, "published")
    with pytest.raises(Stale):
        await run(db, OWNER_P, event, "approve", expected=9)


async def test_view_only_404(db):
    event = await seeded(db, letter="P")
    with pytest.raises(NotFound):
        await run(db, VIEWER, event, "submit")
    visible = await seeded(db, "published", letter="U")
    with pytest.raises(Forbidden):  # visible, not writable
        await run(db, VIEWER, visible, "unpublish")


async def test_a_full_review_cycle_writes_one_revision_each(db):
    cal = (await seed_calendars(db))["I"]
    event = await make(db, OWNER, cal)
    for who, action in (
        (OWNER, "submit"),
        (OWNER_P, "reject"),
        (OWNER, "submit"),
        (OWNER_P, "approve"),
    ):
        await run(db, who, event, action)
    actions = (
        (
            await db.execute(
                select(Revision.action)
                .where(Revision.event_id == event.id)
                .order_by(Revision.number)
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["created", "submitted", "rejected", "submitted", "approved"]
    assert event.revision == 5
