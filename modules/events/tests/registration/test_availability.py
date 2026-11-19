"""``describe``: what one occurrence offers, and the one answer for everything not public (PR 9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_events.core import locales
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, EventText
from sm_events.models.enums import Visibility
from sm_events.registration.availability import Availability, RegistrationEvent, describe
from sqlalchemy import event as sa_event

from tests.registration.support import (
    NOW,
    SECOND,
    SECOND_KEY,
    START,
    moved,
    one_off,
    override,
    public_calendar,
    series,
    taken,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

LATER = NOW + timedelta(days=1)


async def ask(db, event, key=None, *, provider=PROVIDER_ID, target=KNOWN_TARGET, **kw):
    kw.setdefault("locale", "en")
    kw.setdefault("now", NOW)
    return await describe(
        db,
        tenant_id="default",
        event_id=event.id if isinstance(event, Event) else event,
        occurrence_key=key if key is not None else str(event.id),
        provider=provider,
        target=target,
        **kw,
    )


@pytest.fixture
async def cal(db):
    return await public_calendar(db)


async def test_open_one_off(db, cal):
    event = await one_off(db, cal, registration_capacity=10, registration_show_seats=True)
    got = await ask(db, event)
    assert got.state == "open" and got.seats_left == 10
    assert isinstance(got.event, RegistrationEvent)
    assert got.event.event_id == event.id and got.event.occurrence_key == str(event.id)
    assert (got.event.title, got.event.lang) == ("Open day", "en")
    assert (got.event.starts_at, got.event.timezone) == (START, "Europe/Vienna")
    assert got.event.page_path.startswith("/events/event-") and "?date" not in got.event.page_path
    assert got.event.ics_path == got.event.page_path + ".ics"


@pytest.mark.parametrize(
    "case",
    [
        "draft", "in_review", "scheduled", "trashed", "calendar_trashed", "internal", "private",
        "external", "no_mode", "wrong_provider", "wrong_target", "unknown_id", "other_event_key",
        "skipped_key", "not_in_rule", "series_key_on_one_off", "one_off_key_on_series",
    ],
)  # fmt: skip
async def test_unavailable_truth_table(db, case):
    cal = await public_calendar(db, "pub")
    provider, target, key = PROVIDER_ID, KNOWN_TARGET, None
    fields = {}
    if case == "draft":
        fields = {"status": "draft"}
    elif case == "in_review":
        fields = {"status": "in_review"}
    elif case == "scheduled":
        fields = {"status": "in_review", "publish_at": LATER}
    elif case == "trashed":
        fields = {"is_deleted": True}
    elif case == "external":
        fields = {"registration_mode": "external", "registration_url": "https://x.example/r"}
    elif case == "no_mode":
        fields = {"registration_mode": "none", "registration_provider": None}
    elif case == "wrong_provider":
        provider = "other:registration"
    elif case == "wrong_target":
        target = "another-form"
    if case in {"internal", "private"}:
        cal = await public_calendar(
            db, case, visibility=Visibility.INTERNAL if case == "internal" else Visibility.PRIVATE
        )
    if case == "calendar_trashed":
        cal.is_deleted = True
        await db.flush()
    if case in {"skipped_key", "not_in_rule", "one_off_key_on_series"}:
        event = await series(db, cal)
        if case == "skipped_key":
            await override(db, event, "skipped")
            key = SECOND_KEY.format(id=event.id)
        elif case == "not_in_rule":
            key = f"{event.id}:20260709T080000Z"  # a Thursday
        else:
            key = str(event.id)
    else:
        event = await one_off(db, cal, **fields)
    if case == "unknown_id":
        event_id, key = uuid.uuid4(), None
    else:
        event_id = event.id
    if case == "other_event_key":
        key = f"{uuid.uuid4()}"
    if case == "series_key_on_one_off":
        key = f"{event.id}:20260708T080000Z"
    got = await ask(
        db,
        event_id,
        key if key is not None else str(event_id),
        provider=provider,
        target=target,
    )
    assert got == Availability("unavailable", None, None, None, None)


@pytest.mark.parametrize(
    "key",
    [
        "", "x", "not-a-uuid", "A" * 36, f"{uuid.uuid4()}:", f"{uuid.uuid4()}:2026-07-08",
        f"{uuid.uuid4()}:20261308T080000Z", f"{uuid.uuid4()}:20260708T080000Z:extra",
        "x" * 81, f"{uuid.uuid4()} ", None, 5,
    ],
)  # fmt: skip
async def test_a_malformed_key_is_refused_before_any_query(db, cal, key):
    event = await one_off(db, cal)
    statements: list[str] = []
    engine = db.bind.sync_engine

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", count)
    try:
        with pytest.raises(ValueError):
            await describe(
                db,
                tenant_id="default",
                event_id=event.id,
                occurrence_key=key,
                provider=PROVIDER_ID,
                target=KNOWN_TARGET,
                locale="en",
            )
    finally:
        sa_event.remove(engine, "before_cursor_execute", count)
    assert statements == []


@pytest.mark.parametrize("bad", ["", "x", 5, None, "A" * 36])
async def test_a_malformed_event_id_is_refused(db, bad):
    with pytest.raises(ValueError):
        await ask(db, bad, str(uuid.uuid4()))


async def test_states(db, cal):
    event = await one_off(db, cal, registration_capacity=1)
    assert (await ask(db, event)).state == "open"
    event.cancelled = True
    await db.flush()
    got = await ask(db, event)
    assert got.state == "cancelled" and got.event is not None  # the page still says what it was
    event.cancelled = False
    event.registration_opens_at = LATER
    await db.flush()
    got = await ask(db, event)
    assert got.state == "not_open_yet" and got.opens_at == LATER
    event.registration_opens_at, event.registration_closes_at = None, NOW - timedelta(minutes=1)
    await db.flush()
    assert (await ask(db, event)).state == "closed"
    event.registration_closes_at = None
    await db.flush()
    assert (await ask(db, event, now=START)).state == "closed"  # the occurrence has started
    assert (await ask(db, event, now=START - timedelta(seconds=1))).state == "open"
    await taken(db, event, None, 1)
    assert (await ask(db, event)).state == "full"


async def test_the_window_edges(db, cal):
    event = await one_off(
        db,
        cal,
        registration_opens_at=NOW,
        registration_closes_at=NOW + timedelta(hours=1),
    )
    assert (await ask(db, event, now=NOW - timedelta(microseconds=1))).state == "not_open_yet"
    assert (await ask(db, event, now=NOW)).state == "open"  # opens at its instant
    last = NOW + timedelta(hours=1) - timedelta(microseconds=1)
    assert (await ask(db, event, now=last)).state == "open"
    assert (await ask(db, event, now=NOW + timedelta(hours=1))).state == "closed"


async def test_a_series_occurrence_is_cancelled_on_its_own(db, cal):
    event = await series(db, cal, registration_capacity=5)
    await override(db, event, "cancelled")
    cancelled = await ask(db, event, SECOND_KEY.format(id=event.id))
    other = await ask(db, event, f"{event.id}:20260715T080000Z")
    assert cancelled.state == "cancelled" and other.state == "open"


async def test_each_occurrence_has_its_own_seats(db, cal):
    event = await series(db, cal, registration_capacity=1, registration_show_seats=True)
    await taken(db, event, SECOND_KEY.format(id=event.id), 1)
    full = await ask(db, event, SECOND_KEY.format(id=event.id))
    free = await ask(db, event, f"{event.id}:20260715T080000Z")
    assert (full.state, full.seats_left) == ("full", 0)
    assert (free.state, free.seats_left) == ("open", 1)


async def test_the_first_occurrence_of_a_series_has_a_stamped_key(db, cal):
    event = await series(db, cal)
    got = await ask(db, event, f"{event.id}:20260701T080000Z")
    assert got.state == "open" and got.event.starts_at == START
    assert (await ask(db, event, str(event.id))).state == "unavailable"


@pytest.mark.parametrize(
    ("show", "capacity", "used", "expected"),
    [(False, 3, 1, None), (True, 3, 1, 2), (True, 3, 3, 0), (True, 3, 5, 0), (True, None, 4, None)],
)
async def test_seats_left_only_when_shown(db, cal, show, capacity, used, expected):
    event = await one_off(db, cal, registration_capacity=capacity, registration_show_seats=show)
    await taken(db, event, None, used)
    assert (await ask(db, event)).seats_left == expected


async def test_unlimited_capacity_is_never_full(db, cal):
    event = await one_off(db, cal)
    await taken(db, event, None, 10_000)
    assert (await ask(db, event)).state == "open"


async def test_a_lowered_capacity_is_full_not_negative(db, cal):
    event = await one_off(db, cal, registration_capacity=1, registration_show_seats=True)
    await taken(db, event, None, 3)
    got = await ask(db, event)
    assert (got.state, got.seats_left) == ("full", 0)


async def test_moved_occurrence_keeps_its_key_and_shows_the_new_time(db, cal):
    event = await series(db, cal)
    new = datetime(2026, 7, 9, 12, 30, tzinfo=UTC)
    await moved(db, event, new)
    got = await ask(db, event, SECOND_KEY.format(id=event.id), locale="de")
    assert got.state == "open" and got.event.occurrence_key == SECOND_KEY.format(id=event.id)
    assert got.event.starts_at == new and got.event.ends_at == new + timedelta(hours=1)
    assert "Donnerstag" in got.event.when_text  # the 9th: a Thursday, on the new time
    assert got.event.page_path.endswith("?date=2026-07-08")  # the address keeps the original date


async def test_a_moved_occurrence_closes_at_its_new_start(db, cal):
    event = await series(db, cal)
    new = datetime(2026, 7, 9, 12, 30, tzinfo=UTC)
    await moved(db, event, new)
    key = SECOND_KEY.format(id=event.id)
    assert (await ask(db, event, key, now=SECOND + timedelta(hours=2))).state == "open"
    assert (await ask(db, event, key, now=new)).state == "closed"


async def test_when_text(db, cal):
    event = await one_off(db, cal)
    de = (await ask(db, event, locale="de")).event.when_text
    en = (await ask(db, event, locale="en")).event.when_text
    assert "CEST" in de and "Mittwoch" in de and "10:00" in de
    assert "CEST" in en and "Wednesday" in en
    all_day = await one_off(
        db,
        cal,
        title="All day",
        all_day=True,
        starts_at=datetime(2026, 6, 30, 22, tzinfo=UTC),
        ends_at=datetime(2026, 7, 1, 22, tzinfo=UTC),
    )
    text = (await ask(db, all_day, locale="en")).event.when_text
    assert "Wednesday" in text and "CEST" not in text and ":" not in text


async def test_place_and_links(db, cal):
    event = await one_off(
        db,
        cal,
        attendance_mode="hybrid",
        venue_name="Hall",
        address="1 Main St\nVienna",
        online_url="https://meet.example/room",
    )
    got = (await ask(db, event)).event
    assert (got.venue_name, got.address) == ("Hall", "1 Main St\nVienna")
    assert got.online_url == "https://meet.example/room"
    in_person = await one_off(db, cal, title="Other", online_url="https://meet.example/x")
    assert (await ask(db, in_person)).event.online_url is None  # an in-person event has no link


async def test_language_follows_the_request_and_the_site(db, cal):
    event = await one_off(db, cal)
    db.add(
        EventText(event_id=event.id, locale="de", slug="offener-tag", title="Tag der offenen Tür")
    )
    await db.flush()
    locales.use("en", "de")
    de = (await ask(db, event, locale="de")).event
    assert (de.title, de.lang, de.page_path) == (
        "Tag der offenen Tür",
        "de",
        "/de/events/offener-tag",
    )
    assert de.ics_path == "/de/events/offener-tag.ics"
    en = (await ask(db, event, locale="en")).event
    assert en.lang == "en" and en.page_path.startswith("/events/event-")
    fr = (await ask(db, event, locale="fr")).event  # not offered: the site's default language
    assert fr.lang == "en"
    locales.use("en")  # a language the site does not serve is not linked to
    assert (await ask(db, event, locale="de")).event.lang == "en"


async def test_series_page_path_names_the_occurrence(db, cal):
    event = await series(db, cal)
    got = (await ask(db, event, SECOND_KEY.format(id=event.id))).event
    assert got.page_path.endswith("?date=2026-07-08")
    assert got.ics_path.endswith(".ics") and "?" not in got.ics_path


async def test_no_personal_data_in_the_answer(db, cal):
    event = await one_off(db, cal, registration_capacity=3, registration_show_seats=True)
    got = await ask(db, event)
    flat = repr(got)
    for forbidden in ("holder", "@", "email"):
        assert forbidden not in flat


async def test_tenant_pinned(db, cal):
    event = await one_off(db, cal)
    with pytest.raises(TenantIsolationError):
        await describe(
            db,
            tenant_id="b",
            event_id=event.id,
            occurrence_key=str(event.id),
            provider=PROVIDER_ID,
            target=KNOWN_TARGET,
            locale="en",
        )


@pytest.mark.unbound_tenant
async def test_another_tenants_event_is_unavailable(db_state):
    with tenant_scope("b"):
        async with db_state.session_factory() as db:
            cal = Calendar(slug="pub", name="Pub", owner_id="o", visibility=Visibility.PUBLIC)
            db.add(cal)
            await db.flush()
            event = await one_off(db, cal)
            event_id = event.id
            await db.commit()
    for tenant, expected in (("b", "open"), ("a", "unavailable"), ("default", "unavailable")):
        async with db_state.session_factory() as db:
            got = await describe(
                db,
                tenant_id=tenant,
                event_id=event_id,
                occurrence_key=str(event_id),
                provider=PROVIDER_ID,
                target=KNOWN_TARGET,
                locale="en",
                now=NOW,
            )
        assert got.state == expected, tenant


@pytest.mark.unbound_tenant
async def test_an_unbound_session_is_bound_by_the_call(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cal = await public_calendar(db)
            event = await one_off(db, cal)
            event_id = event.id
            await db.commit()
    async with db_state.session_factory() as db:  # no tenant bound here
        got = await describe(
            db,
            tenant_id="default",
            event_id=event_id,
            occurrence_key=str(event_id),
            provider=PROVIDER_ID,
            target=KNOWN_TARGET,
            locale="en",
            now=NOW,
        )
    assert got.state == "open"
