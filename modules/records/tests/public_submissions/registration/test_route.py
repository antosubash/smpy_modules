"""``GET …/{type}/registration``: availability, and a token only while the occurrence is open."""

from __future__ import annotations

import uuid

import pytest

from tests.support.public_submissions_support import create
from tests.support.registration_http import TYPE, load_registration, registration_type, seed_event
from tests.support.submissions_http import SUBMISSIONS

pytestmark = pytest.mark.usefixtures("reg_site")


async def test_route_open(reg_site):
    resp = await load_registration(reg_site, reg_site.event, locale="de")
    assert resp.status_code == 200 and resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["availability"] == {
        "state": "open",
        "seats_left": None,
        "few_left": False,
        "opens_at": None,
        "closes_at": None,
    }
    assert body["event"]["title"] == "Open day" and "2099" in body["event"]["when_text"]
    definition = body["definition"]
    assert definition["kind"] == "registration" and definition["double_opt_in"] is True
    assert len(definition["token"].split(".")) == 6
    assert [f["key"] for f in definition["fields"]] == ["sm_name", "sm_email", "diet"]
    assert definition["consent"] is None and "holder" not in resp.text


async def test_seats_left_only_when_the_event_shows_them(reg_site):
    shown = await seed_event(
        reg_site.db_state, registration_show_seats=True, uid="b@x", registration_capacity=5
    )
    body = (await load_registration(reg_site, shown)).json()
    assert body["availability"]["seats_left"] == 5


async def test_route_states(reg_site):
    from datetime import UTC, datetime

    closed = await seed_event(
        reg_site.db_state,
        uid="c@x",
        registration_closes_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    body = (await load_registration(reg_site, closed)).json()
    assert body["availability"]["state"] == "closed" and body["definition"] is None
    assert body["event"]["title"] == "Open day"
    full = await seed_event(reg_site.db_state, uid="d@x", registration_capacity=1)
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import RegistrationCount

    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            db.add(
                RegistrationCount(
                    event_id=uuid.UUID(full["event_id"]), occurrence_key=full["key"], taken=1
                )
            )
            await db.commit()
    body = (await load_registration(reg_site, full)).json()
    assert (body["availability"]["state"], body["definition"]) == ("full", None)


async def test_a_disabled_type_is_closed(reg_site):
    from tests.support.public_submissions_support import update

    off = await update(
        reg_site,
        TYPE,
        public_submissions={"kind": "registration", "enabled": False, "public_fields": ["diet"]},
    )
    assert off.status_code == 200, off.text
    body = (await load_registration(reg_site, reg_site.event)).json()
    assert body["availability"]["state"] == "closed" and body["definition"] is None


async def test_unavailable_everything_is_one_404(reg_site):
    draft = await seed_event(reg_site.db_state, uid="e@x", status="draft")
    external = await seed_event(
        reg_site.db_state,
        uid="f@x",
        registration_mode="external",
        registration_target=None,
        registration_provider=None,
    )
    other_target = await seed_event(reg_site.db_state, uid="g@x", registration_target="elsewhere")
    await create(reg_site, "contact")
    cases = [
        await load_registration(reg_site, draft),
        await load_registration(reg_site, external),
        await load_registration(reg_site, other_target),
        await load_registration(reg_site, reg_site.event, key="nope"),
        await load_registration(reg_site, reg_site.event, key="contact"),  # a form-kind type
        await load_registration(
            reg_site, {"event_id": "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42", "key": "x"}
        ),
        await load_registration(
            reg_site,
            {"event_id": reg_site.event["event_id"], "key": reg_site.event["event_id"] + "x"},
        ),
        await load_registration(reg_site, {"event_id": "nope", "key": "nope"}),
    ]
    shapes = {(r.status_code, r.text, r.headers["cache-control"]) for r in cases}
    assert len(shapes) == 1 and next(iter(shapes))[0] == 404


async def test_a_series_key_for_a_one_off_is_the_same_404(reg_site):
    ev = reg_site.event
    resp = await reg_site.get(
        f"{SUBMISSIONS}/{TYPE}/registration",
        params={"event": ev["event_id"], "occurrence": f"{ev['event_id']}:20990701T080000Z"},
    )
    unknown = await reg_site.get(f"{SUBMISSIONS}/nope/registration", params={"event": "x"})
    assert resp.status_code == 404 and resp.text == unknown.text


async def test_missing_query_is_the_same_404(reg_site):
    resp = await reg_site.get(f"{SUBMISSIONS}/{TYPE}/registration")
    unknown = await reg_site.get(f"{SUBMISSIONS}/nope/registration")
    assert resp.status_code == 404 and resp.text == unknown.text


@pytest.mark.unbound_tenant
async def test_route_tenant(reg_site):
    """Another tenant's event, asked through this host's tenant, is the 404."""
    other = await seed_event(reg_site.db_state, tenant="b", uid="h@x")
    assert (await load_registration(reg_site, other)).status_code == 404
    assert registration_type
