"""Shared fixtures for the records tests.

Deliberately database-only: the index layer is SQL, and everything it has to
get right — the truncation re-check, EXISTS over a multi-valued field, the
soft-delete filter applying to a join it never mentions — is visible with a
session and nothing else. The app, the auth stub and the HTTP client arrive
with the endpoints that need them; adding them now would make every index test
depend on routing that does not exist yet.

Two things are load-bearing and easy to drop when extending this file:

``StaticPool``, so every session in a test talks to the *same* ``:memory:``
database — the default pool opens a fresh, empty one per connection.

``register_listeners``, because the soft-delete filter is an ORM execute hook,
not a column default. Without it a soft-deleted record is returned by every
query here and the tests that prove otherwise pass for the wrong reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
from sm_records.models import Record, RecordType
from sm_records.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy.ext.asyncio import AsyncSession

# ``app_harness`` is the HTTP test harness — app + client fixtures,
# header-driven roles, and DB seeding helpers for API/view tests. Split into
# its own module for the 300-line cap; importing the names here is what makes
# pytest see them as fixtures in this directory.
#
# ``pg_support`` owns the one decision both database fixtures make: in-memory
# SQLite, or the Postgres database ``RECORDS_TEST_URL`` names.
from tests.app_harness import (  # noqa: F401 - re-exported as fixtures/helpers
    ADMIN,
    ROLE_EDITOR,
    ROLE_EDITOR_TWO,
    ROLE_MANAGER,
    ROLE_NONE,
    ROLE_VIEWER,
    client,
    records_app,
    roles,
    seed_record,
    seed_type,
)

# Fixtures several suites share, each defined once beside what it builds on.
from tests.bulk_helpers import product  # noqa: F401
from tests.census import Census, census_enabled
from tests.events_harness import bus, note  # noqa: F401
from tests.isolation_support import two_tenants  # noqa: F401 - the tenancy matrix's fixture
from tests.pg_support import arm_reset, make_db_state
from tests.shared_fixtures import (  # noqa: F401
    bilingual,
    file_client,
    file_db,
    order_type,
    public_client,
    settings,
)


@pytest.fixture(autouse=True)
def _default_tenant(request):
    """Every test runs inside ``tenant_scope(DEFAULT_TENANT)`` — what a
    single-tenant host binds (tenancy design §A.3, §K "Harness").

    Every records table the ORM writes carries ``MultiTenantMixin``, whose
    column is ``NOT NULL`` and stamped from the bound tenant at flush, so a
    fixture that inserts a type or a record needs one. Synchronous and autouse
    so it is set up before any async fixture: pytest-asyncio runs each async
    fixture and test in a *copy* of this context, so the binding reaches all of
    them — and, through ``httpx.ASGITransport``, which runs the app in the
    test's own task, every request the test makes. That is also why the
    harness needs no request middleware for it.

    ``@pytest.mark.unbound_tenant`` opts a test out, for the ones that are
    about what happens with no tenant bound.
    """
    if request.node.get_closest_marker("unbound_tenant") is not None:
        yield None
        return
    with tenant_scope(DEFAULT_TENANT) as tenant:
        yield tenant


@pytest.fixture(scope="session")
def _census() -> Iterator[Census | None]:
    if not census_enabled():
        yield None
        return
    census = Census()
    census.install()
    yield census
    census.remove()


@pytest.fixture(autouse=True)
def _statement_census(request, _census):
    """Tenancy design K12: fail a test in which ``sm_records`` sent a statement
    naming a tenant-owned table without ``tenant_id`` (``tests/census.py``).
    On by default on Postgres only."""
    yield
    if _census is not None:
        caught = _census.take(request.node.nodeid)
        assert not caught, "records statement(s) with no tenant_id:\n" + "\n".join(
            f"{where}: {sql[:300]}" for where, sql in caught
        )


@pytest.fixture(autouse=True)
def _arm_database_reset():
    """Every test starts from an empty database.

    A no-op on SQLite, where each test builds its own ``:memory:`` one and
    there is nothing to empty. On Postgres it is what makes the *first*
    database a test asks for a clean one — see
    :func:`tests.pg_support.arm_reset` for why the emptying is armed here
    rather than done on every ``make_db_state``.

    Autouse and synchronous, so it is set up before any of the async database
    fixtures that read the flag it sets.
    """
    arm_reset()
    yield


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    """In-memory SQLite by default; Postgres when ``RECORDS_TEST_URL`` says so.

    The construction moved to :func:`tests.pg_support.make_db_state` so that
    this fixture and ``app_harness.build_app`` — the suite's two entry points
    into a database — cannot drift apart about which backend is in use. On
    SQLite it is exactly what it was: ``StaticPool`` over ``:memory:``, with
    the soft-delete listeners registered.
    """
    state = await make_db_state()
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def db(db_state) -> AsyncIterator[AsyncSession]:
    async with db_state.session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Each test's in-memory database hands out ``type_id`` 1 afresh, so two
    tests that both create type id 1 with different fields would otherwise
    share one compiled validator — a collision production ids never produce."""
    from sm_records.schema.compile import clear_model_cache

    clear_model_cache()
    yield
    clear_model_cache()


@pytest.fixture(autouse=True)
def _clean_providers():
    """The index-provider registry is process-global (design doc §7.6), so a
    test that registers one changes what every later test's records index to.

    ``clear()`` also drops the virtual fields those providers declared — and
    with them the "already warned about this type" memo behind
    ``providers.note_shadowed`` — so a test asserting the shadowing warning
    sees it whatever ran before, and a test declaring a field keyed like some
    other test's virtual field is not refused by a registration that outlived
    it.

    ``reduce_providers`` go with them, and for the same reason twice over: a
    reduce spec left registered writes a delta on every later test's record
    write, and its key stays reserved against a declared field of that name.
    """
    from sm_records.index import providers
    from sm_records.index.reduce import clear_reduce_providers

    providers.clear()
    clear_reduce_providers()
    yield
    providers.clear()
    clear_reduce_providers()


async def create_type(db: AsyncSession, key: str, fields: list[dict], **cols) -> RecordType:
    """Insert a record type. Flushed, not committed — the fixtures share one
    session and the tests read back through it."""
    rtype = RecordType(
        key=key,
        label=cols.pop("label", key.title()),
        label_plural=cols.pop("label_plural", f"{key.title()}s"),
        fields=fields,
        **cols,
    )
    db.add(rtype)
    await db.flush()
    return rtype


async def create_record(db: AsyncSession, rtype: RecordType, data: dict, **cols) -> Record:
    """Insert a record of ``rtype``, stamped with the type's current schema
    version the way a real write does."""
    record = Record(
        type_id=rtype.id,
        data=data,
        schema_version=cols.pop("schema_version", rtype.schema_version),
        **cols,
    )
    db.add(record)
    await db.flush()
    return record


@pytest.fixture
def make_type(db):
    """``await make_type(key, fields)`` — ``create_type`` curried onto the
    test's session, so a test body never repeats it."""

    async def _make(key: str, fields: list[dict], **cols) -> RecordType:
        return await create_type(db, key, fields, **cols)

    return _make


@pytest.fixture
def make_record(db):
    async def _make(rtype: RecordType, data: dict, **cols) -> Record:
        return await create_record(db, rtype, data, **cols)

    return _make


@pytest.fixture
def field_def():
    """Build one raw field definition — the JSON shape ``RecordType.fields``
    stores (design doc §6.1), not a schema object: the index layer reads stored
    definitions and the tests should hand it exactly what the column holds."""

    def _def(key: str, type_: str, *, indexed: bool = True, **options) -> dict:
        return {
            "key": key,
            "type": type_,
            "label": key.replace("_", " ").title(),
            "required": False,
            "unique": False,
            "indexed": indexed,
            "default": None,
            "help": None,
            "constraints": {},
            "options": options,
        }

    return _def


@pytest.fixture
def resolver():
    """``resolve_type_id`` over a dict of types — a stand-in for the lookup the
    service layer will do against ``records_type``."""

    def _build(**types) -> Any:
        ids = {key: rtype.id for key, rtype in types.items()}
        return ids.get

    return _build
