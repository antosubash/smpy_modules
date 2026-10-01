"""Natural-key lookups and the create stamp — tenancy design §E and §F.

Where a caller's string becomes a row — a type key, a record uuid, a slug, the
public reads, an import's match — records says the tenant in the statement
rather than resting on the framework's loader criteria. Under a bound tenant
the two agree, so what these pin is the behaviour (``acme`` and ``globex``
share the key ``post`` and one uuid, and each sees its own) and one thing only
the explicit form gives: with no tenant bound the lookup is ``TenantUnbound``
even on a session the guard was never installed on.

§F: every create sets ``tenant_id`` from its type, so a context in another
tenant is the framework's ``TenantIsolationError`` — before the composite
foreign key, which SQLite does not enforce by default (L15), would have to.
"""

from __future__ import annotations

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_records._tenant_guard import is_guarded
from sm_records.models import RecordStatus
from sm_records.services import public as public_service
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._import_match import MATCH_UUID, resolve_matches
from sm_records.services._import_parse import ImportRow
from sm_records.services.errors import NotFound
from sm_records.tenancy import TenantUnbound

from tests.tenancy_support import SAME_UUID, SETTINGS, Tenant, seed_tenant, session_in

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def two(db_state) -> tuple[Tenant, Tenant]:
    return await seed_tenant(db_state, "acme"), await seed_tenant(db_state, "globex")


async def test_a_type_key_resolves_in_the_bound_tenant(db_state, two):
    for tenant in two:
        async with session_in(db_state, tenant.name) as session:
            assert (await type_service.get_type(session, "post")).id == tenant.rtype.id
    _, globex = two
    async with session_in(db_state, "acme") as session:
        with pytest.raises(NotFound):
            await type_service.get_type_by_id(session, globex.rtype.id)


async def test_a_type_key_taken_in_another_tenant_is_free_here(db_state, two):
    async with session_in(db_state, "initech") as session:
        rtype = await type_service.create_type(session, key="post", label="P", settings=SETTINGS)
        assert rtype.tenant_id == "initech"


async def test_a_shared_uuid_resolves_to_the_bound_tenants_record(db_state, two):
    for tenant in two:
        async with session_in(db_state, tenant.name) as session:
            rtype = await type_service.get_type(session, "post")
            found = await record_service.get_record(session, rtype, SAME_UUID)
            assert (found.id, found.data["title"]) == (tenant.record.id, tenant.name)


async def test_an_import_matches_a_shared_uuid_in_the_bound_tenant_only(db_state, two):
    """The uuid match is not scoped by type (it spans the table set), so the
    tenant is the only thing between it and the other tenant's row."""
    rows = [ImportRow(number=1, envelope={"uuid": SAME_UUID})]
    for tenant in two:
        async with session_in(db_state, tenant.name) as session:
            matched = await resolve_matches(
                session, tenant.rtype, rows, match_by=MATCH_UUID, defs=[]
            )
            assert matched[1].id == tenant.record.id


async def test_the_public_reads_resolve_in_the_bound_tenant(db_state, two):
    for tenant in two:
        async with session_in(db_state, tenant.name) as session:
            rtype = await type_service.get_type(session, "post")
            rtype.is_public = True
            record = await record_service.get_record(session, rtype, SAME_UUID)
            record.status = RecordStatus.PUBLISHED
    for tenant in two:
        async with session_in(db_state, tenant.name) as session:
            rtype = await public_service.get_public_type(session, "post")
            assert rtype.id == tenant.rtype.id
            one = await public_service.get_public_record(
                session, rtype, SAME_UUID, settings=SETTINGS
            )
            page = await public_service.list_public_records(
                session, rtype, settings=SETTINGS, locale="en"
            )
            assert [item.id for item in page.items] == [one.id] == [tenant.record.id]


async def test_an_unbound_lookup_is_refused_without_the_guard(db_state):
    """``db_state`` never had the guard put on its session class: what refuses
    here is the lookup's own ``bound_tenant()``."""
    assert not is_guarded(db_state.sync_session_class)
    async with db_state.session_factory() as session:
        with pytest.raises(TenantUnbound):
            await type_service.get_type(session, "post")
        with pytest.raises(TenantUnbound):
            await public_service.get_public_type(session, "post")


async def test_a_create_under_another_tenant_is_refused_by_the_stamp(db_state, two):
    _, globex = two
    async with session_in(db_state, "acme") as session:
        with pytest.raises(TenantIsolationError):
            await record_service.create_record(
                session, globex.rtype, data={"title": "stray"}, settings=SETTINGS
            )
        await session.rollback()


async def test_a_create_is_stamped_with_its_types_tenant(db_state, two):
    acme, _ = two
    async with session_in(db_state, "acme") as session:
        record = await record_service.create_record(
            session, acme.rtype, data={"title": "new"}, settings=SETTINGS
        )
        assert record.tenant_id == "acme"
