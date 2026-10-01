"""The tenant-owned schema at the service level — design §B, §C, K8 and K9.

* **K8, per-tenant uniqueness.** Two tenants may share a type key and a record
  uuid (an export from one imported into the other keeps its uuids); inside
  one tenant each is still the conflict it always was.
* **K9, the composite foreign key.** ``(type_id, tenant_id) -> records_type
  (id, tenant_id)``: a record can never sit in a different tenant from its
  type, whatever the code above the database gets wrong. SQLite enforces it
  only with ``PRAGMA foreign_keys=ON``, which this switches on for the session
  that tries.

Each tenant gets its own session: ``tenant_scope`` refuses to re-bind within a
scope, and one session serving two tenants is how the identity map would leak.
"""

from __future__ import annotations

import json

import pytest
from sm_records.contracts.io import ImportFormat
from sm_records.models import Record, RecordType
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._claims import flush_write
from sm_records.services.errors import Conflict
from sm_records.services.import_ import ImportOptions, import_records
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.unbound_tenant

SETTINGS = RecordsSettings()
FIELDS = [{"key": "title", "type": "text", "label": "Title", "indexed": True}]
FILE_UUID = "0" * 31 + "1"


async def _new_type(db_state, tenant: str, key: str = "note") -> RecordType:
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            rtype = await type_service.create_type(
                session, key=key, label="Note", fields_raw=FIELDS, settings=SETTINGS
            )
            await session.commit()
            return rtype


async def test_two_tenants_may_both_have_a_type_keyed_note(db_state):
    acme = await _new_type(db_state, "acme")
    globex = await _new_type(db_state, "globex")
    assert acme.id != globex.id
    assert (acme.tenant_id, globex.tenant_id) == ("acme", "globex")


async def test_inside_one_tenant_a_taken_type_key_is_still_the_409(db_state):
    await _new_type(db_state, "acme")
    with pytest.raises(Conflict, match="already exists"):
        await _new_type(db_state, "acme")


async def test_the_database_refuses_a_duplicate_key_inside_a_tenant(db_state):
    """What closes the race behind the service's check."""
    await _new_type(db_state, "acme")
    with tenant_scope("acme"):
        async with db_state.session_factory() as session:
            session.add(RecordType(key="note", label="N", label_plural="Ns", fields=[]))
            with pytest.raises(IntegrityError):
                await session.flush()


def _file(title: str) -> str:
    return json.dumps(
        {"type": {"key": "note"}, "records": [{"uuid": FILE_UUID, "data": {"title": title}}]}
    )


async def _import(db_state, tenant: str, rtype: RecordType, title: str):
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            report = await import_records(
                session,
                rtype,
                _file(title),
                fmt=ImportFormat.JSON,
                options=ImportOptions(match_by="uuid", dry_run=False, force=True),
                settings=SETTINGS,
            )
            await session.commit()
            return report


async def test_an_import_keeps_its_uuid_in_each_tenant_it_is_imported_into(db_state):
    acme, globex = await _new_type(db_state, "acme"), await _new_type(db_state, "globex")
    assert (await _import(db_state, "acme", acme, "A")).created == 1
    assert (await _import(db_state, "globex", globex, "G")).created == 1
    # Inside one tenant the uuid is the same record again: an update, not a
    # second row — the match the importer has always made.
    assert (await _import(db_state, "acme", acme, "A2")).updated == 1
    for tenant, title in (("acme", "A2"), ("globex", "G")):
        with tenant_scope(tenant):
            async with db_state.session_factory() as session:
                rows = (await session.execute(select(Record).where(Record.uuid == FILE_UUID))).all()
                assert [row[0].data["title"] for row in rows] == [title]


async def test_a_uuid_race_inside_one_tenant_is_a_409_and_across_tenants_is_legal(db_state):
    acme, globex = await _new_type(db_state, "acme"), await _new_type(db_state, "globex")
    with tenant_scope("acme"):
        async with db_state.session_factory() as session:
            first = await record_service.create_record(
                session, acme, data={"title": "one"}, settings=SETTINGS
            )
            taken = first.uuid
            await session.commit()
            second = await record_service.create_record(
                session, acme, data={"title": "two"}, settings=SETTINGS
            )
            second.uuid = taken
            with pytest.raises(Conflict, match="uuid"):
                await flush_write(session, acme, None, "en")
            await session.rollback()
    with tenant_scope("globex"):
        async with db_state.session_factory() as session:
            other = await record_service.create_record(
                session, globex, data={"title": "three"}, settings=SETTINGS
            )
            other.uuid = taken
            await flush_write(session, globex, None, "en")
            await session.commit()


async def _enforce_foreign_keys(session) -> None:
    if not USING_POSTGRES:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_a_record_cannot_belong_to_another_tenants_type(db_state):
    default = await _new_type(db_state, "default")
    with tenant_scope("acme"):
        async with db_state.session_factory() as session:
            await _enforce_foreign_keys(session)
            # Stamped ``acme`` by the framework's flush listener; its type is
            # ``default``'s. Only the composite key can see the disagreement.
            session.add(Record(type_id=default.id, data={}, schema_version=1))
            with pytest.raises(IntegrityError):
                await session.flush()
    with tenant_scope("default"):
        async with db_state.session_factory() as session:
            await _enforce_foreign_keys(session)
            session.add(Record(type_id=default.id, data={}, schema_version=1))
            await session.flush()
            assert (await session.execute(select(Record.tenant_id))).scalar() == "default"
