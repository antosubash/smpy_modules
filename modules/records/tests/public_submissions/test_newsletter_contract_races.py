"""Two unsubscribes of one subscriber attribute it once (spec amendment 8).

``unsubscribe`` answers whether *this* call wrote — the transition's
``Outcome.wrote`` — not whether the status reads ``unsubscribed`` afterwards,
so of two callers (the one-click POST and the reconcile, say) exactly one
records the unsubscribe as its own and one event is published. On SQLite the
race is forced at the write, as in ``test_public_submissions_newsletter_races``;
Postgres also runs two real transactions at once. Plus ``set_tags``' one
retry when the row moved under it.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_records.contracts.newsletter import set_tags, unsubscribe
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.models import tables_for
from sm_records.public_submissions import campaign_writes
from sm_records.public_submissions import transition as transition_module
from sm_records.records.services.errors import Conflict
from sqlalchemy import update

from tests.pg_support import USING_POSTGRES
from tests.support.newsletter_contract import (
    TENANT,
    session,
    subscription_events,
    transitions,
    unsubscribe_committed,
    uuid_of,
)
from tests.support.newsletter_http import LIST

SETTINGS = RecordsSettings()


async def _call(client, db, uuid: str) -> bool:
    return await unsubscribe(
        db,
        tenant_id=TENANT,
        type_key=LIST,
        uuid=uuid,
        unless_confirmed_after=None,
        settings=SETTINGS,
        bus=client.app.state.sm.event_bus,
    )


async def _force(db, rtype, record, **values) -> None:
    """Write ``values`` onto the row behind the service's back, as a competing
    transaction would."""
    cls = tables_for(rtype).record
    await db.execute(
        update(cls)
        .where(cls.id == record.id, cls.tenant_id == record.tenant_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


async def test_two_sessions_one_after_the_other(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    seen = subscription_events(audience)
    async with session(audience) as first, session(audience) as second:
        assert await _call(audience, first, uuid) is True
        await events.commit(first)
        assert await _call(audience, second, uuid) is False
        await events.commit(second)
    assert list(transitions(seen)) == [("confirmed", "unsubscribed")]


async def test_a_competitor_that_wrote_first_makes_this_call_false(audience, monkeypatch):
    """The row moves to ``unsubscribed`` just before this call's write lands:
    its version check fails, it decides again from the moved row, and says it
    did not write — although the status it leaves is ``unsubscribed``."""
    uuid = await uuid_of(audience, "ada@example.org")
    seen = subscription_events(audience)
    real = transition_module.record_service.update_record
    moved: list[bool] = []

    async def racing(db, rtype, record, **kw):
        if not moved:
            moved.append(True)
            data = {**record.data, "sm_status": "unsubscribed"}
            await _force(db, rtype, record, data=data, version=record.version + 1)
        return await real(db, rtype, record, **kw)

    monkeypatch.setattr(transition_module.record_service, "update_record", racing)
    assert await unsubscribe_committed(audience, uuid) is False
    assert moved and seen == []


@pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")
async def test_two_unsubscribes_at_once_attribute_it_once(audience):
    uuid = await uuid_of(audience, "ada@example.org")
    seen = subscription_events(audience)
    answers = await asyncio.gather(
        unsubscribe_committed(audience, uuid), unsubscribe_committed(audience, uuid)
    )
    assert sorted(answers) == [False, True]
    assert list(transitions(seen)) == [("confirmed", "unsubscribed")]


async def test_set_tags_retries_once_when_the_row_moved(audience, monkeypatch):
    """An edit that lands between the read and the write (a version bump) is
    read again and the tags merged onto it; a second miss is ``Conflict``."""
    uuid = await uuid_of(audience, "ada@example.org")
    real = campaign_writes.record_service.update_record
    calls: list[int] = []

    async def bumped(db, rtype, record, **kw):
        calls.append(kw["expected_version"])
        if len(calls) == 1:
            await _force(db, rtype, record, version=record.version + 1)
        return await real(db, rtype, record, **kw)

    monkeypatch.setattr(campaign_writes.record_service, "update_record", bumped)
    async with session(audience) as db:
        hit = await set_tags(
            db, tenant_id=TENANT, type_key=LIST, uuid=uuid, add=["b"], settings=SETTINGS
        )
        await events.commit(db)
    assert hit.tags == ["a", "b"] and calls == [calls[0], calls[0] + 1]

    async def always_moved(db, rtype, record, **kw):
        raise Conflict("moved")

    monkeypatch.setattr(campaign_writes.record_service, "update_record", always_moved)
    async with session(audience) as db:
        with pytest.raises(Conflict):
            await set_tags(
                db, tenant_id=TENANT, type_key=LIST, uuid=uuid, remove=["a"], settings=SETTINGS
            )
