"""Seats: arguments are checked, the tenant is pinned, and the locale fills the event."""

from __future__ import annotations

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sm_events.models.enums import Visibility
from sm_events.registration.seats import (
    admit,
    counts,
    release,
    release_target,
    seat_holders,
)

from tests.registration.seat_helpers import PROVIDER, rows, take
from tests.registration.support import (
    NOW,
    consistent,
    one_off,
)
from tests.support.providers import KNOWN_TARGET


@pytest.mark.parametrize(
    "kw",
    [
        {"holder": ""}, {"holder": 5}, {"holder": None}, {"holder": "x" * 65}, {"holder": "a\nb"},
        {"admin": 1}, {"admin": None}, {"occurrence_key": "x"}, {"event_id": "nope"},
        {"provider": ""}, {"target": "x" * 101},
    ],
)  # fmt: skip
async def test_admit_arguments_are_checked(db, cal, kw):
    event = await one_off(db, cal)
    args = {
        "tenant_id": "default",
        "event_id": event.id,
        "occurrence_key": str(event.id),
        "provider": PROVIDER,
        "target": KNOWN_TARGET,
        "holder": "h1",
        **kw,
    }
    with pytest.raises(ValueError):
        await admit(db, **args)
    assert await rows(db) == []


async def test_holder_length_edge(db, cal):
    event = await one_off(db, cal)
    assert (await take(db, event, "h" * constants.REGISTRATION_HOLDER_MAX)).admitted


async def test_release_and_page_arguments_are_checked(db):
    base = {"tenant_id": "default", "provider": PROVIDER}
    for bad in ([], [""], ["a"] * 0, "abc", [1], ["x" * 65]):
        with pytest.raises(ValueError):
            await release(db, holders=bad, **base)
    with pytest.raises(ValueError):
        await release(db, holders=[f"h{n}" for n in range(constants.SEAT_RELEASE_MAX + 1)], **base)
    await release(db, holders=[f"h{n}" for n in range(constants.SEAT_RELEASE_MAX)], **base)
    for limit in (0, -1, True, constants.SEAT_HOLDERS_MAX + 1, "5", None):
        with pytest.raises(ValueError):
            await seat_holders(db, after=None, limit=limit, **base)
    await seat_holders(db, after=None, limit=constants.SEAT_HOLDERS_MAX, **base)
    await seat_holders(db, after=None, limit=1, **base)
    for after in ("", 5, "x" * 65):
        with pytest.raises(ValueError):
            await seat_holders(db, after=after, limit=1, **base)
    with pytest.raises(ValueError):
        await release_target(db, target="", **base)


async def test_tenant_pinned(db, cal):
    event = await one_off(db, cal)
    with pytest.raises(TenantIsolationError):
        await admit(
            db,
            tenant_id="b",
            event_id=event.id,
            occurrence_key=str(event.id),
            provider=PROVIDER,
            target=KNOWN_TARGET,
            holder="h1",
        )
    for call in (
        release(db, tenant_id="b", provider=PROVIDER, holders=["h1"]),
        release_target(db, tenant_id="b", provider=PROVIDER, target=KNOWN_TARGET),
        seat_holders(db, tenant_id="b", provider=PROVIDER, after=None, limit=1),
        counts(db, tenant_id="b", event_id=event.id),
    ):
        with pytest.raises(TenantIsolationError):
            await call


@pytest.mark.unbound_tenant
async def test_tenants_keep_their_seats_apart(db_state):
    ids = {}
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                cal = Calendar(slug="pub", name="Pub", owner_id="o", visibility=Visibility.PUBLIC)
                db.add(cal)
                await db.flush()
                event = await one_off(db, cal, registration_capacity=1)
                ids[tenant] = event.id
                await db.commit()
    for tenant in ("a", "b"):  # the same holder id, one seat each
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                got = await admit(
                    db,
                    tenant_id=tenant,
                    event_id=ids[tenant],
                    occurrence_key=str(ids[tenant]),
                    provider=PROVIDER,
                    target=KNOWN_TARGET,
                    holder="same-holder",
                    now=NOW,
                )
                assert got.admitted
                await db.commit()
    with tenant_scope("a"):  # another tenant's event is not there to admit to
        async with db_state.session_factory() as db:
            got = await admit(
                db,
                tenant_id="a",
                event_id=ids["b"],
                occurrence_key=str(ids["b"]),
                provider=PROVIDER,
                target=KNOWN_TARGET,
                holder="h9",
                now=NOW,
            )
            assert (got.admitted, got.code) == (False, "event_unavailable")
            assert await release(db, tenant_id="a", provider=PROVIDER, holders=["same-holder"]) == 1
            await db.commit()
    with tenant_scope("b"):
        async with db_state.session_factory() as db:
            assert [r.holder for r in await rows(db)] == ["same-holder"]
            await consistent(db)


async def test_locale_fills_the_event_for_the_caller(db, cal):
    event = await one_off(db, cal)
    got = await take(db, event, "h1", locale="de")
    assert got.admitted and got.event is not None and got.event.lang == "en"
    assert "Mittwoch" in got.event.when_text
    refused = await take(db, event, "h1", locale="de", target="nope")
    assert refused.event is None
