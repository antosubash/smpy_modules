"""``contracts.registration``: the surface, the checks that run before any SQL, the tenant it pins,
and ``summaries`` (PR 9)."""

from __future__ import annotations

import uuid

import pytest
from sm_events.contracts import registration as contract
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope

from tests.registration.support import (
    NOW,
    one_off,
    public_calendar,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID
from tests.support.sql_spy import Spy

EXPECTED = [
    "Admission",
    "Availability",
    "EVENT_UNAVAILABLE",
    "REGISTRATION_CLOSED",
    "REGISTRATION_FULL",
    "RegistrationEvent",
    "SEAT_RELEASE_MAX",
    "SeatRef",
    "SeatsBusy",
    "admit",
    "describe",
    "release",
    "release_target",
    "seat_holders",
    "summaries",
    "format_instant",
]


def test_contract_surface():
    assert sorted(contract.__all__) == sorted(EXPECTED)
    for name in contract.__all__:
        assert hasattr(contract, name)
    assert (
        contract.REGISTRATION_FULL,
        contract.REGISTRATION_CLOSED,
        contract.EVENT_UNAVAILABLE,
    ) == (
        "registration_full",
        "registration_closed",
        "event_unavailable",
    )
    assert contract.REGISTRATION_FULL == constants.REGISTRATION_FULL


def calls(db, *, tenant="default", event_id=None, **over):
    """Every contract function with valid arguments, ``over`` replacing any of them."""
    eid = event_id or uuid.uuid4()
    base = {
        "tenant_id": tenant,
        "event_id": eid,
        "occurrence_key": str(eid),
        "provider": PROVIDER_ID,
        "target": KNOWN_TARGET,
        "holder": "h1",
        "holders": ["h1"],
        "after": None,
        "limit": 10,
        "locale": "en",
        "refs": [(eid, str(eid))],
    }
    base.update(over)
    pick = lambda *names: {n: base[n] for n in names}  # noqa: E731
    return {
        "describe": contract.describe(
            db, **pick("tenant_id", "event_id", "occurrence_key", "provider", "target", "locale")
        ),
        "admit": contract.admit(
            db,
            **pick("tenant_id", "event_id", "occurrence_key", "provider", "target", "holder"),
        ),
        "release": contract.release(db, **pick("tenant_id", "provider", "holders")),
        "release_target": contract.release_target(db, **pick("tenant_id", "provider", "target")),
        "seat_holders": contract.seat_holders(
            db, **pick("tenant_id", "provider", "after", "limit")
        ),
        "summaries": contract.summaries(db, **pick("tenant_id", "provider", "refs", "locale")),
    }


@pytest.mark.parametrize(
    ("over", "names"),
    [
        ({"limit": True}, ["seat_holders"]),
        ({"limit": 0}, ["seat_holders"]),
        ({"limit": constants.SEAT_HOLDERS_MAX + 1}, ["seat_holders"]),
        ({"holder": ""}, ["admit"]),
        ({"holders": [""]}, ["release"]),
        ({"holders": []}, ["release"]),
        ({"holders": [f"h{n}" for n in range(constants.SEAT_RELEASE_MAX + 1)]}, ["release"]),
        ({"event_id": "not-a-uuid"}, ["describe", "admit"]),
        ({"occurrence_key": "nope"}, ["describe", "admit"]),
        ({"provider": ""}, ["describe", "admit", "release", "release_target", "seat_holders"]),
        ({"target": ""}, ["describe", "admit", "release_target"]),
        ({"locale": ""}, ["describe"]),
        ({"after": ""}, ["seat_holders"]),
        (
            {"refs": [(uuid.uuid4(), "x")]},
            ["summaries"],
        ),
        ({"refs": "x"}, ["summaries"]),
        (
            {
                "refs": [
                    (uuid.uuid4(), str(uuid.uuid4())) for _ in range(constants.SUMMARIES_MAX + 1)
                ]
            },
            ["summaries"],
        ),
        ({"tenant_id": "a\n"}, ["*"]),
        ({"tenant_id": ""}, ["*"]),
        ({"tenant_id": "x" * 51}, ["*"]),
        ({"tenant_id": "platform"}, ["*"]),
    ],
)
async def test_arguments_checked(db_state, db, over, names):
    with Spy(db_state) as spy:
        built = calls(db, **over)
        targets = list(built) if names == ["*"] else names
        for name in built:
            if name not in targets:
                built[name].close()  # not under test: never awaited
                continue
            with pytest.raises(ValueError):
                await built[name]
    assert spy.seen == []


async def test_valid_arguments_pass_the_checks(db):
    built = calls(db, limit=constants.SEAT_HOLDERS_MAX)
    assert await built["seat_holders"] == []
    for name in ("describe", "admit", "release", "release_target", "summaries"):
        built[name].close()


@pytest.mark.unbound_tenant
async def test_binds_its_tenant(db_state):
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            cal = await public_calendar(db)
            event = await one_off(db, cal, registration_capacity=2)
            event_id = event.id
            await db.commit()
    async with db_state.session_factory() as db:  # nothing bound on this session
        key = str(event_id)
        avail = await contract.describe(
            db,
            tenant_id="default",
            event_id=event_id,
            occurrence_key=key,
            provider=PROVIDER_ID,
            target=KNOWN_TARGET,
            locale="en",
            now=NOW,
        )
        assert avail.state == "open"
        got = await contract.admit(
            db,
            tenant_id="default",
            event_id=event_id,
            occurrence_key=key,
            provider=PROVIDER_ID,
            target=KNOWN_TARGET,
            holder="h1",
            now=NOW,
        )
        assert got.admitted
        page = await contract.seat_holders(
            db, tenant_id="default", provider=PROVIDER_ID, after=None, limit=5
        )
        assert [(p.holder, p.event_id) for p in page] == [("h1", event_id)]
        found = await contract.summaries(
            db,
            tenant_id="default",
            provider=PROVIDER_ID,
            refs=[(event_id, key)],
            locale="en",
        )
        assert found[(event_id, key)] is not None
        assert (
            await contract.release(db, tenant_id="default", provider=PROVIDER_ID, holders=["h1"])
            == 1
        )
        await db.commit()
    with tenant_scope("other"):  # another tenant sees none of it
        async with db_state.session_factory() as db:
            assert (
                await contract.seat_holders(
                    db, tenant_id="other", provider=PROVIDER_ID, after=None, limit=5
                )
                == []
            )


async def test_other_bound_tenant_refused(db):
    from simple_module_db.listeners import TenantIsolationError

    for call in calls(db, tenant="b").values():
        with pytest.raises(TenantIsolationError):
            await call
