"""The fail-closed guard — ``sm_records.tenancy.install_guard`` (design §A.4, K5).

Ported from spike 1g onto the real models: with the guard on the session class,
records ORM work with no tenant bound is an error that names the bug, instead
of the framework's answers — every tenant's rows on a read (FACT 1b), a
``NOT NULL`` 500 on an insert (FACT 1a) and a silent tenant move on an update
(FACT 1a‴). Not installed at startup yet (Phase 3); these prove it works when
it is.
"""

from __future__ import annotations

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records._tenant_guard import is_guarded, owned
from sm_records.models import IndexText, Record, RecordRevision, RecordType, RecordTypeRevision
from sm_records.tenancy import TenantUnbound, all_tenants, install_guard, tenant_scope
from sqlalchemy import func, select

pytestmark = pytest.mark.unbound_tenant


async def _seed(db_state) -> dict[str, int]:
    """A ``post`` type and one record in each of two tenants, each in its own
    session — ``tenant_scope`` refuses to re-bind within one, by design."""
    ids: dict[str, int] = {}
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            async with db_state.session_factory() as session:
                rtype = RecordType(key="post", label="Post", label_plural="Posts", fields=[])
                session.add(rtype)
                await session.flush()
                record = Record(type_id=rtype.id, data={}, schema_version=1)
                session.add(record)
                await session.commit()
                ids[tenant] = record.id
    return ids


@pytest.fixture
async def guarded(db_state):
    install_guard(db_state.sync_session_class)
    install_guard(db_state.sync_session_class)  # idempotent
    return db_state


def test_only_records_tenant_owned_classes_are_guarded():
    assert all(owned(cls) for cls in (RecordType, RecordTypeRevision, Record, RecordRevision))
    assert not owned(IndexText), "index rows are derived and carry no tenant (§B)"


async def test_install_is_idempotent_and_per_session_class(guarded, db_state):
    assert is_guarded(guarded.sync_session_class)


async def test_an_unbound_read_is_refused(guarded):
    await _seed(guarded)
    async with guarded.session_factory() as session:
        with pytest.raises(TenantUnbound, match="RecordType"):
            await session.execute(select(RecordType).where(RecordType.key == "post"))
        with pytest.raises(TenantUnbound):
            await session.execute(select(func.count(Record.id)))


async def test_an_explicit_cross_tenant_read_is_allowed(guarded):
    await _seed(guarded)
    async with guarded.session_factory() as session:
        stmt = all_tenants(select(RecordType.tenant_id).order_by(RecordType.tenant_id))
        assert (await session.execute(stmt)).scalars().all() == ["acme", "globex"]


async def test_a_bound_read_passes_and_the_framework_filter_still_applies(guarded):
    ids = await _seed(guarded)
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            assert (await session.execute(select(Record.id))).scalars().all() == [ids["acme"]]
            # ``all_tenants`` only lets a statement past the guard; bound, the
            # framework's own tenant criteria still narrow it.
            tagged = all_tenants(select(RecordType.tenant_id))
            assert (await session.execute(tagged)).scalars().all() == ["acme"]


async def test_core_statements_are_invisible_to_it(guarded):
    """The documented hole (1g): which is why §E makes an explicit
    ``tenant_id`` predicate mandatory on Core, ``text()`` and DML."""
    await _seed(guarded)
    async with guarded.session_factory() as session:
        rows = (await session.execute(select(Record.__table__.c.id))).all()
    assert len(rows) == 2


async def test_an_unbound_insert_is_refused_even_with_an_explicit_tenant(guarded):
    """Unbound, the framework accepts any explicit ``tenant_id`` (FACT 1a-prime)."""
    async with guarded.session_factory() as session:
        session.add(RecordType(key="x", label="X", label_plural="Xs", tenant_id="acme"))
        with pytest.raises(TenantUnbound, match="written with no tenant bound"):
            await session.flush()


async def test_an_unbound_update_cannot_move_a_row(guarded):
    """Unbound, the framework refuses the move before records' guard sees the
    flush (framework 0.0.35, #356); before it, the refusal was the guard's."""
    ids = await _seed(guarded)
    async with guarded.session_factory() as session:
        stmt = all_tenants(select(Record).where(Record.id == ids["acme"]))
        record = (await session.execute(stmt)).scalar_one()
        record.tenant_id = "globex"
        with pytest.raises(TenantIsolationError, match="Cannot change tenant_id"):
            await session.flush()


async def test_a_bound_update_cannot_move_a_row_either(guarded):
    """Bound, the refusal is the framework's own (FACT 1a‴)."""
    ids = await _seed(guarded)
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            record = await session.get(Record, ids["acme"])
            record.tenant_id = "globex"
            with pytest.raises(TenantIsolationError):
                await session.flush()


async def test_an_unbound_delete_is_refused(guarded):
    ids = await _seed(guarded)
    async with guarded.session_factory() as session:
        stmt = all_tenants(select(Record).where(Record.id == ids["globex"]))
        record = (await session.execute(stmt)).scalar_one()
        await session.delete(record)
        with pytest.raises(TenantUnbound):
            await session.flush()
