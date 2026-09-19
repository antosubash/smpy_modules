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

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.models import Base, Record, RecordType
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def db(db_state) -> AsyncIterator[AsyncSession]:
    async with db_state.session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _clean_providers():
    """The index-provider registry is process-global (design doc §7.6), so a
    test that registers one changes what every later test's records index to.
    """
    from sm_records.index import providers

    providers.clear()
    yield
    providers.clear()


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
