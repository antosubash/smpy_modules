"""The retention sweep (#101, design §10): old contact-form submissions and
never-confirmed newsletter signups are purged, per tenant, through the purge
paths (so their delivery claims go with them and ``RecordPurged`` fires),
and a second sweeper does nothing. Delivery pruning and the eligibility
re-check are in ``test_public_submissions_retention_rules.py``."""

from __future__ import annotations

import pytest
from simple_module_core.leases import lease
from sm_records.contracts.events import RecordPurged, RecordTrashed
from sm_records.public_submissions import retention
from sm_records.services import records as record_service
from sm_records.services import types as type_service

from tests.retention_support import (
    NOW,
    Bus,
    S,
    claim,
    claims,
    form,
    newsletter,
    record,
    subscriber,
    sweep,
    temp_db,
    uuids,
)
from tests.tenancy_support import session_in

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def db(tmp_path):
    async with temp_db(tmp_path) as state:
        yield state


async def test_form_submissions_past_retention_go_trash_included(db):
    await form(db, retention_days=30)
    old = await record(db, "contact", age_days=31)
    spam = await record(db, "contact", age_days=40, trashed=True)
    third = await record(db, "contact", age_days=35)
    fresh = await record(db, "contact", age_days=29)
    await claim(db, old, sent=NOW)
    await claim(db, fresh, sent=NOW)
    bus = Bus()

    swept = await sweep(db, bus)

    assert swept is not None and swept.purged == 3 and swept.tenants == ["default"]
    assert await uuids(db, "contact") == {fresh}
    # The purge path forgot the purged record's claim, not the live one's.
    assert await claims(db) == [(fresh, "ops@x.org")]
    purged = {e.uuid for e in bus.published if isinstance(e, RecordPurged)}
    trashed = {e.uuid for e in bus.published if isinstance(e, RecordTrashed)}
    assert purged == {old, spam, third}
    assert trashed == {old, third}, "a live record is trashed first, then purged"


async def test_zero_retention_keeps_everything(db):
    await form(db, retention_days=0)
    kept = await record(db, "contact", age_days=3650)
    assert (await sweep(db)).purged == 0
    assert await uuids(db, "contact") == {kept}


async def test_only_never_confirmed_signups_past_the_purge_age_go(db):
    await newsletter(db)
    pending_old = await record(db, "news", age_days=31, **subscriber("pending"))
    pending_trashed = await record(db, "news", age_days=31, trashed=True, **subscriber("pending"))
    pending_new = await record(db, "news", age_days=29, **subscriber("pending"))
    confirmed = await record(db, "news", age_days=400, **subscriber("confirmed"))
    gone = await record(db, "news", age_days=400, **subscriber("unsubscribed"))

    swept = await sweep(db)

    assert swept.purged == 2
    assert await uuids(db, "news") == {pending_new, confirmed, gone}
    assert pending_old not in await uuids(db, "news")
    assert pending_trashed not in await uuids(db, "news")


async def test_every_tenant_is_swept_in_its_own_scope(db):
    for tenant in ("acme", "globex"):
        await form(db, tenant, retention_days=10)
        await record(db, "contact", age_days=11, tenant=tenant)
        keep = await record(db, "contact", age_days=1, tenant=tenant)
        assert len(await uuids(db, "contact", tenant)) == 2
        assert keep

    swept = await sweep(db)

    assert swept.tenants == ["acme", "globex"] and swept.purged == 2
    for tenant in ("acme", "globex"):
        assert len(await uuids(db, "contact", tenant)) == 1


async def test_a_second_sweeper_finds_the_lease_held_and_the_sweep_is_idempotent(db):
    await form(db, retention_days=1)
    await record(db, "contact", age_days=2)
    other = lease(retention.LEASE_NAME, ttl=60, blocking=False)
    assert await other.acquire()
    try:
        assert await sweep(db) is None
        assert len(await uuids(db, "contact")) == 1, "nothing purged while another sweeps"
    finally:
        await other.release()
    assert (await sweep(db)).purged == 1
    assert (await sweep(db)).purged == 0


async def test_a_record_another_type_restricts_is_skipped_not_forced(db):
    await form(db, retention_days=1)
    blocked = await record(db, "contact", age_days=5)
    freed = [await record(db, "contact", age_days=5) for _ in range(3)]
    async with session_in(db, "default") as session:
        ref = {
            "key": "about",
            "type": "relation",
            "label": "About",
            "indexed": True,
            "options": {"target_type": "contact", "on_delete": "restrict"},
        }
        note = await type_service.create_type(
            session, key="note", label="Note", settings=S, fields_raw=[ref]
        )
        await record_service.create_record(
            session, note, data={"about": {"type": "contact", "uuid": blocked}}, settings=S
        )

    swept = await sweep(db)

    assert swept.skipped == 1 and swept.purged == len(freed)
    assert await uuids(db, "contact") == {blocked}
