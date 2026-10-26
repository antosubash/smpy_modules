"""The retention sweep (#101, design §10): old contact-form submissions and
never-confirmed newsletter signups are purged, per tenant, through the purge
paths (so their delivery claims go with them and ``RecordPurged`` fires),
old delivery bookkeeping is pruned, and a second sweeper does nothing."""

from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from simple_module_core.leases import lease
from sm_records.contracts.events import RecordPurged, RecordTrashed
from sm_records.models import SubmissionDelivery, tables_for
from sm_records.public_submissions import retention
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings
from sqlalchemy import select, update

from tests.app_harness import build_app
from tests.public_submissions_support import contact_fields, form_config
from tests.tenancy_support import session_in

pytestmark = pytest.mark.unbound_tenant

S = RecordsSettings(reindex_batch_size=2)
NOW = utcnow()
DATA = {"name": "Ada", "email": "ada@example.org", "message": "Hello"}


class Bus:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


@pytest.fixture
async def db(tmp_path):
    _, db_state = await build_app(tmp_path)
    yield db_state
    await db_state.engine.dispose()


async def _form(db, tenant: str = "default", key: str = "contact", **config):
    async with session_in(db, tenant) as session:
        return await type_service.create_type(
            session,
            key=key,
            label=key.title(),
            settings=S,
            fields_raw=contact_fields(),
            public_submissions=form_config(enabled=True, **config),
        )


async def _list(db, tenant: str = "default", key: str = "news"):
    async with session_in(db, tenant) as session:
        return await type_service.create_type(
            session,
            key=key,
            label=key.title(),
            settings=S,
            fields_raw=[],
            public_submissions={"kind": "subscription", "enabled": True},
        )


async def _record(db, key: str, *, age_days: float, tenant="default", trashed=False, **system):
    """A record of ``key`` whose ``created_at`` and ``updated_at`` are
    ``age_days`` in the past; its uuid."""
    async with session_in(db, tenant) as session:
        rtype = await type_service.get_type(session, key)
        data = {} if rtype.public_submissions["kind"] == "subscription" else dict(DATA)
        record = await record_service.create_record(
            session, rtype, data=data, settings=S, system=system or None
        )
        if trashed:
            await record_service.soft_delete_record(session, rtype, record, settings=S)
        cls = tables_for(rtype).record
        then = NOW - timedelta(days=age_days)
        await session.execute(
            update(cls)
            .where(cls.id == record.id, cls.tenant_id == tenant)
            .values(created_at=then, updated_at=then)
            .execution_options(include_deleted=True)
        )
        return record.uuid


def _subscriber(status: str) -> dict:
    return {
        "sm_email": f"{secrets.token_hex(4)}@example.org",
        "sm_status": status,
        "sm_nonce": secrets.token_hex(16),
    }


async def _uuids(db, key: str, tenant: str = "default") -> set[str]:
    async with session_in(db, tenant) as session:
        rtype = await type_service.get_type(session, key)
        cls = tables_for(rtype).record
        stmt = select(cls.uuid).where(cls.type_id == rtype.id, cls.tenant_id == tenant)
        rows = await session.execute(stmt.execution_options(include_deleted=True))
        return set(rows.scalars().all())


async def _claim(db, uuid: str, *, tenant="default", sent=None, claimed=None, who="ops@x.org"):
    async with session_in(db, tenant) as session:
        session.add(
            SubmissionDelivery(
                tenant_id=tenant,
                record_uuid=uuid,
                attempt=secrets.token_hex(8),
                recipient=who,
                claimed_at=claimed,
                sent_at=sent,
            )
        )


async def _claims(db, tenant: str = "default") -> list[tuple[str, str]]:
    async with session_in(db, tenant) as session:
        table = SubmissionDelivery
        rows = await session.execute(
            select(table.record_uuid, table.recipient).where(table.tenant_id == tenant)
        )
        return sorted((str(a), str(b)) for a, b in rows.all())


async def _sweep(db, bus=None, settings: RecordsSettings = S):
    return await retention.sweep(db.session_factory, settings, bus=bus, now=NOW)


async def test_form_submissions_past_retention_go_trash_included(db):
    await _form(db, retention_days=30)
    old = await _record(db, "contact", age_days=31)
    spam = await _record(db, "contact", age_days=40, trashed=True)
    third = await _record(db, "contact", age_days=35)
    fresh = await _record(db, "contact", age_days=29)
    await _claim(db, old, sent=NOW)
    await _claim(db, fresh, sent=NOW)
    bus = Bus()

    swept = await _sweep(db, bus)

    assert swept is not None and swept.purged == 3 and swept.tenants == ["default"]
    assert await _uuids(db, "contact") == {fresh}
    # The purge path forgot the purged record's claim, not the live one's.
    assert await _claims(db) == [(fresh, "ops@x.org")]
    purged = {e.uuid for e in bus.published if isinstance(e, RecordPurged)}
    trashed = {e.uuid for e in bus.published if isinstance(e, RecordTrashed)}
    assert purged == {old, spam, third}
    assert trashed == {old, third}, "a live record is trashed first, then purged"


async def test_zero_retention_keeps_everything(db):
    await _form(db, retention_days=0)
    kept = await _record(db, "contact", age_days=3650)
    assert (await _sweep(db)).purged == 0
    assert await _uuids(db, "contact") == {kept}


async def test_only_never_confirmed_signups_past_the_purge_age_go(db):
    await _list(db)
    pending_old = await _record(db, "news", age_days=31, **_subscriber("pending"))
    pending_trashed = await _record(db, "news", age_days=31, trashed=True, **_subscriber("pending"))
    pending_new = await _record(db, "news", age_days=29, **_subscriber("pending"))
    confirmed = await _record(db, "news", age_days=400, **_subscriber("confirmed"))
    gone = await _record(db, "news", age_days=400, **_subscriber("unsubscribed"))

    swept = await _sweep(db)

    assert swept.purged == 2
    assert await _uuids(db, "news") == {pending_new, confirmed, gone}
    assert pending_old not in await _uuids(db, "news")
    assert pending_trashed not in await _uuids(db, "news")


async def test_every_tenant_is_swept_in_its_own_scope(db):
    for tenant in ("acme", "globex"):
        await _form(db, tenant, retention_days=10)
        await _record(db, "contact", age_days=11, tenant=tenant)
        keep = await _record(db, "contact", age_days=1, tenant=tenant)
        assert len(await _uuids(db, "contact", tenant)) == 2
        assert keep

    swept = await _sweep(db)

    assert swept.tenants == ["acme", "globex"] and swept.purged == 2
    for tenant in ("acme", "globex"):
        assert len(await _uuids(db, "contact", tenant)) == 1


async def test_a_second_sweeper_finds_the_lease_held_and_the_sweep_is_idempotent(db):
    await _form(db, retention_days=1)
    await _record(db, "contact", age_days=2)
    other = lease(retention.LEASE_NAME, ttl=60, blocking=False)
    assert await other.acquire()
    try:
        assert await _sweep(db) is None
        assert len(await _uuids(db, "contact")) == 1, "nothing purged while another sweeps"
    finally:
        await other.release()
    assert (await _sweep(db)).purged == 1
    assert (await _sweep(db)).purged == 0


async def test_a_record_another_type_restricts_is_skipped_not_forced(db):
    await _form(db, retention_days=1)
    blocked = await _record(db, "contact", age_days=5)
    freed = [await _record(db, "contact", age_days=5) for _ in range(3)]
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

    swept = await _sweep(db)

    assert swept.skipped == 1 and swept.purged == len(freed)
    assert await _uuids(db, "contact") == {blocked}


async def test_old_delivery_rows_are_pruned_and_live_claims_kept(db):
    await _form(db, retention_days=0)
    uuid = await _record(db, "contact", age_days=0)
    days = S.public_submissions_delivery_retention_days
    old = NOW - timedelta(days=days + 1)
    await _claim(db, uuid, sent=old, who="sent-long-ago")
    await _claim(db, uuid, sent=NOW, who="sent-today")
    await _claim(db, uuid, claimed=NOW, who="claim-held")
    await _claim(db, uuid, claimed=old, who="claim-expired")
    await _claim(db, uuid, who="claim-released")
    await _claim(db, "f" * 32, tenant="acme", sent=NOW, who="acme-today")

    swept = await _sweep(db)

    assert swept.deliveries == 3
    assert [who for _, who in await _claims(db)] == ["claim-held", "sent-today"]
    assert await _claims(db, "acme") == [("f" * 32, "acme-today")]
