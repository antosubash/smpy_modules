"""``admit`` decides on the event as it is under the lock, not as an earlier read in the same
session saw it (Postgres: the identity map would otherwise answer with the stale row)."""

from __future__ import annotations

import pytest
from sm_events.contracts import registration as contract
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, OccurrenceOverride
from sm_events.registration import args
from sqlalchemy import select, update

from tests.pg_support import USING_POSTGRES
from tests.registration.support import NOW
from tests.registration.test_seats_pg import seeded, try_admit
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="needs real concurrent transactions")


def call(db, event_id, key, **kw):
    return {
        "tenant_id": "default",
        "event_id": event_id,
        "occurrence_key": key,
        "provider": PROVIDER_ID,
        "target": KNOWN_TARGET,
        **kw,
    }


async def committed(state, *statements):
    with tenant_scope("default"):
        async with state.session_factory() as other:
            for statement in statements:
                await other.execute(statement)
            await other.commit()


async def describe_then_change_then_admit(state, event_id, key, *statements):
    with tenant_scope("default"):
        async with state.session_factory() as db:
            seen = await contract.describe(db, **call(db, event_id, key), locale="en", now=NOW)
            assert seen.state == "open"
            # Keep the ORM rows alive (as any caller holding the event would), so the identity map
            # still has them when ``admit`` reads again.
            held = [await db.get(Event, event_id)]
            held += list((await db.execute(select(OccurrenceOverride))).scalars())
            await committed(state, *statements)
            got = await contract.admit(db, **call(db, event_id, key), holder="late", now=NOW)
            assert held
            return got


async def test_a_capacity_lowered_meanwhile_is_honoured(db_state):
    event_id, key = await seeded(db_state, capacity=5)
    assert (await try_admit(db_state, event_id, key, "first")).admitted
    lowered = update(Event).where(Event.id == event_id).values(registration_capacity=1)
    got = await describe_then_change_then_admit(db_state, event_id, key, lowered)
    assert (got.admitted, got.code) == (False, contract.REGISTRATION_FULL)


async def test_an_event_cancelled_meanwhile_refuses(db_state):
    event_id, key = await seeded(db_state, capacity=5)
    cancelled = update(Event).where(Event.id == event_id).values(cancelled=True)
    got = await describe_then_change_then_admit(db_state, event_id, key, cancelled)
    assert (got.admitted, got.code) == (False, contract.REGISTRATION_CLOSED)


async def test_an_occurrence_override_changed_meanwhile_is_honoured(db_state):
    event_id, key = await seeded(db_state, capacity=5, series_event=True, rule="FREQ=DAILY")
    original = args.parse_stamp(key.split(":", 1)[1])
    with tenant_scope("default"):
        async with db_state.session_factory() as db:
            db.add(
                OccurrenceOverride(
                    event_id=event_id,
                    original_start=original,
                    kind="moved",
                    starts_at=original,
                    ends_at=original.replace(hour=original.hour + 1),
                )
            )
            await db.commit()
    cancelled = (
        update(OccurrenceOverride)
        .where(OccurrenceOverride.event_id == event_id)
        .values(kind="cancelled", starts_at=None, ends_at=None)
    )
    got = await describe_then_change_then_admit(db_state, event_id, key, cancelled)
    assert (got.admitted, got.code) == (False, contract.REGISTRATION_CLOSED)
