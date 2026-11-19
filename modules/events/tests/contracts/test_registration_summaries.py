"""``contracts.registration.summaries``: one answer per reference, a fixed cost."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sm_events.contracts import registration as contract
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar
from sm_events.models.enums import Visibility

from tests.registration.support import (
    SECOND_KEY,
    START,
    moved,
    one_off,
    override,
    public_calendar,
    series,
)
from tests.support.providers import PROVIDER_ID
from tests.support.sql_spy import Spy


async def summarise(db, refs, locale="en", provider=PROVIDER_ID):
    return await contract.summaries(
        db, tenant_id="default", provider=provider, refs=refs, locale=locale
    )


async def test_summaries(db):
    cal = await public_calendar(db)
    hidden_cal = await public_calendar(db, "hidden", visibility=Visibility.PRIVATE)
    open_event = await one_off(db, cal, title="Open")
    weekly = await series(db, cal)
    skipped_key = SECOND_KEY.format(id=weekly.id)
    await override(db, weekly, "skipped")
    third = f"{weekly.id}:20260715T080000Z"
    cancelled = f"{weekly.id}:20260722T080000Z"
    await override(db, weekly, "cancelled", datetime(2026, 7, 22, 8, tzinfo=UTC))
    draft = await one_off(db, cal, title="Draft", status="draft")
    private = await one_off(db, hidden_cal, title="Private")
    external = await one_off(
        db, cal, title="Ext", registration_mode="external", registration_url="https://x.example/"
    )
    other = await one_off(db, cal, title="Other", registration_provider="other:registration")
    refs = [
        (open_event.id, str(open_event.id)),
        (weekly.id, third),
        (weekly.id, cancelled),
        (weekly.id, skipped_key),
        (weekly.id, f"{weekly.id}:20260709T080000Z"),  # not in the rule
        (draft.id, str(draft.id)),
        (private.id, str(private.id)),
        (external.id, str(external.id)),
        (other.id, str(other.id)),
        (uuid.uuid4(), str(uuid.uuid4())),
    ]
    got = await summarise(db, refs)
    assert set(got) == set(refs)
    assert got[refs[0]].title == "Open" and got[refs[0]].starts_at == START
    assert got[refs[1]].occurrence_key == third and got[refs[1]].title == "Weekly"
    assert got[refs[2]] is not None  # a cancelled occurrence still says what it was
    for ref in refs[3:]:
        assert got[ref] is None, ref


async def test_summaries_follow_moves_and_the_language(db):
    cal = await public_calendar(db)
    weekly = await series(db, cal)
    key = SECOND_KEY.format(id=weekly.id)
    new = datetime(2026, 7, 9, 12, 30, tzinfo=UTC)
    await moved(db, weekly, new)
    got = await summarise(db, [(weekly.id, key)], locale="de")
    event = got[(weekly.id, key)]
    assert event.starts_at == new and "Donnerstag" in event.when_text


async def test_summaries_of_one_providers_events_only(db):
    cal = await public_calendar(db)
    event = await one_off(db, cal)
    ref = (event.id, str(event.id))
    assert (await summarise(db, [ref]))[ref] is not None
    assert (await summarise(db, [ref], provider="other:registration"))[ref] is None


async def test_summaries_bounds(db):
    assert await summarise(db, []) == {}
    refs = [(uuid.uuid4(), str(uuid.uuid4())) for _ in range(constants.SUMMARIES_MAX)]
    assert set(await summarise(db, refs)) == set(refs)  # the limit itself
    for bad in ("x", None, [("x", "y")], [(uuid.uuid4(),)], [(uuid.uuid4(), 5)]):
        with pytest.raises(ValueError):
            await summarise(db, bad)


async def test_summaries_cost_does_not_grow_with_the_refs(db_state, db):
    cal = await public_calendar(db)
    events = [await one_off(db, cal, title=f"E{n}") for n in range(30)]
    refs = [(e.id, str(e.id)) for e in events]
    with Spy(db_state) as few:
        await summarise(db, refs[:2])
    with Spy(db_state) as many:
        await summarise(db, refs)
    assert len(many.seen) == len(few.seen) <= 6


async def test_summaries_carry_no_personal_data(db):
    cal = await public_calendar(db)
    event = await one_off(db, cal)
    got = (await summarise(db, [(event.id, str(event.id))]))[(event.id, str(event.id))]
    assert "@" not in repr(got) and "holder" not in repr(got)


@pytest.mark.unbound_tenant
async def test_summaries_never_cross_tenants(db_state):
    ids = {}
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            async with db_state.session_factory() as db:
                cal = Calendar(slug="pub", name="Pub", owner_id="o", visibility=Visibility.PUBLIC)
                db.add(cal)
                await db.flush()
                ids[tenant] = (await one_off(db, cal)).id
                await db.commit()
    async with db_state.session_factory() as db:
        ref = (ids["b"], str(ids["b"]))
        got = await contract.summaries(
            db, tenant_id="a", provider=PROVIDER_ID, refs=[ref], locale="en"
        )
    assert got == {ref: None}
