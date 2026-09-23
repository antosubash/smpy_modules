"""The explicit ``tenant_id`` predicates of tenancy design §E, service by service.

The framework's tenant filter reaches only ORM selects that name a tenant-owned
mapper at the top level (FACT 1c/1d/1e). A Core statement over ``__table__``,
an ``UPDATE``/``DELETE`` and a mapper inside ``in_()`` get nothing from it, so
each such site in records says its tenant itself. Most of them are keyed by ids
that came from a filtered read, so no *request* could reach another tenant's
row through them; each test here therefore hands the service another tenant's
row directly — the out-of-band case the predicate is for — or, where the
statement's effect cannot be observed, reads the SQL it sent.

``acme`` and ``globex`` share a type key and a record uuid
(:mod:`tests.tenancy_support`).
"""

from __future__ import annotations

import pytest
from sm_records.models import RecordType, RevisionEvent, tables_for
from sm_records.schema.types import IndexKind
from sm_records.services import _invalid, _lock, _referrer_page
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._common import guarded_bump
from sm_records.services._empty_trash import _purge_ids
from sm_records.services._lifecycle import hard_delete_record, purge_type_records
from sm_records.services.revisions import write_revision
from sm_records.tenancy import all_tenants
from sqlalchemy import insert, select

from tests.tenancy_support import (
    SETTINGS,
    Tenant,
    owned_writes,
    seed_tenant,
    session_in,
    statements,
    unscoped_writes,
)

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def two(db_state) -> tuple[Tenant, Tenant]:
    return await seed_tenant(db_state, "acme"), await seed_tenant(db_state, "globex")


async def _survives(db_state, tenant: Tenant) -> tuple[bool, int]:
    """Is ``tenant``'s record still there, and how many revisions does it have?"""
    tables = tables_for(tenant.rtype)
    async with session_in(db_state, tenant.name) as session:
        found = await session.get(
            tables.record, tenant.record.id, execution_options={"include_deleted": True}
        )
        revisions = (
            await session.execute(
                select(tables.revision.id).where(tables.revision.record_id == tenant.record.id)
            )
        ).all()
    return found is not None, len(revisions)


async def _ref_row(db_state, referrer: Tenant, target: Tenant) -> None:
    """A ref index row from ``referrer``'s record to ``target``'s — the row
    no write path produces across tenants, written the way a script would."""
    table = tables_for(referrer.rtype).index[IndexKind.REF].__table__
    async with session_in(db_state, referrer.name) as session:
        await session.execute(
            insert(table).values(
                record_id=referrer.record.id,
                type_id=referrer.rtype.id,
                field_key="author",
                target_uuid=target.record.uuid,
                target_type_id=target.rtype.id,
            )
        )


async def test_the_referrer_page_counts_only_the_bound_tenants_referrers(db_state, two):
    acme, globex = two
    await _ref_row(db_state, globex, acme)
    async with session_in(db_state, "acme") as session:
        rows = _referrer_page.pair_rows(tables_for(acme.rtype), acme.record)
        assert await _referrer_page.set_counts(session, rows, []) == (0, 0, 0)
        assert await _referrer_page.pair_page(session, rows, [], offset=0, limit=10) == []

    # The control: the same forged row inside one tenant is counted.
    async with session_in(db_state, "acme") as session:
        other = await record_service.create_record(
            session, acme.rtype, data={"title": "b"}, settings=SETTINGS
        )
        referrer = Tenant("acme", acme.rtype, other)
    await _ref_row(db_state, referrer, acme)
    async with session_in(db_state, "acme") as session:
        rows = _referrer_page.pair_rows(tables_for(acme.rtype), acme.record)
        assert await _referrer_page.set_counts(session, rows, []) == (1, 1, 1)


async def test_the_empty_trash_delete_leaves_another_tenants_row(db_state, two):
    acme, globex = two
    async with session_in(db_state, "acme") as session:
        await _purge_ids(session, acme.rtype, [globex.record.id])
    assert await _survives(db_state, globex) == (True, 1)


async def test_the_type_purge_leaves_another_tenants_documents_and_revisions(db_state, two):
    acme, globex = two
    async with session_in(db_state, "acme") as session:
        assert await purge_type_records(session, globex.rtype) == []
    assert await _survives(db_state, globex) == (True, 1)
    assert await _survives(db_state, acme) == (True, 1)


async def test_the_invalid_mark_leaves_another_tenants_row(db_state, two):
    acme, globex = two
    async with session_in(db_state, "acme") as session:
        await _invalid.write_marks(session, acme.rtype, mark=[globex.record])
    cls = tables_for(globex.rtype).record
    async with session_in(db_state, "globex") as session:
        stmt = select(cls.invalid_since).where(cls.id == globex.record.id)
        assert (await session.execute(stmt)).scalar_one() is None


async def test_the_optimistic_bump_cannot_move_another_tenants_version(db_state, two):
    _, globex = two
    async with session_in(db_state, "acme") as session:
        bumped = await guarded_bump(session, RecordType, globex.rtype.id, globex.rtype.version)
        assert bumped is False
    async with session_in(db_state, "globex") as session:
        stmt = all_tenants(select(RecordType.version).where(RecordType.id == globex.rtype.id))
        assert (await session.execute(stmt)).scalar_one() == globex.rtype.version


async def test_the_type_lock_names_its_tenant(db_state, two):
    acme, _ = two
    async with session_in(db_state, "acme") as session:
        with statements(db_state) as seen:
            await _lock.lock_type(session, acme.rtype)
    assert any("records_type" in sql for sql in seen)
    assert all("tenant_id" in sql for sql in seen if "records_type" in sql), seen


async def test_the_hard_delete_statements_name_their_tenant(db_state, two):
    acme, _ = two
    async with session_in(db_state, "acme") as session:
        record = await record_service.get_record(session, acme.rtype, acme.record.uuid)
        record.is_deleted = True
        await session.flush()
        with statements(db_state) as seen:
            await hard_delete_record(session, acme.rtype, record)
    assert owned_writes(seen), seen
    assert unscoped_writes(seen) == []


async def test_the_type_delete_and_revision_prune_name_their_tenant(db_state, two):
    acme, _ = two
    async with session_in(db_state, "acme") as session:
        record = await record_service.get_record(session, acme.rtype, acme.record.uuid)
        with statements(db_state) as pruned:
            for _ in range(2):
                await write_revision(session, record, RevisionEvent.UPDATE, limit=1)
            await session.flush()
        with statements(db_state) as deleted:
            await type_service.delete_type(session, acme.rtype, confirm_record_count=1)
    for seen in (pruned, deleted):
        assert owned_writes(seen), seen
        assert unscoped_writes(seen) == []
