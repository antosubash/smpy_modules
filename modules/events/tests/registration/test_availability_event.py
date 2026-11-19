"""``describe``: the event facts it carries (text, place, links) and the tenant it pins."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_events.core import locales
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, EventText
from sm_events.models.enums import Visibility
from sm_events.registration.availability import describe

from tests.registration.support import (
    NOW,
    SECOND_KEY,
    one_off,
    public_calendar,
    series,
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
