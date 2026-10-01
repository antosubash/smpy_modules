"""Two tenants in one database, for the service-level tenancy tests.

``acme`` and ``globex`` each get a type keyed ``post`` and one record whose
uuid is **the same string** in both — the collision per-tenant uniqueness
allows (design §C), and exactly the ambiguity an explicit ``tenant_id``
predicate exists to resolve. Each tenant is written on its own session inside
its own ``tenant_scope``, because one session serving two tenants is how the
identity map leaks (§E).

Also :func:`statements`, the statement census of design K12 narrowed to one
call: which SQL a service actually sent, so a test can assert that a ``DELETE``
or ``UPDATE`` of a tenant-owned table carries ``tenant_id`` — the only proof
there is for a Core statement whose ids already came from a filtered read.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from sm_records.models import Record, RecordType
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope
from sqlalchemy import event

SETTINGS = RecordsSettings()
FIELDS = [{"key": "title", "type": "text", "label": "Title", "indexed": True}]
SAME_UUID = "0" * 31 + "7"
OWNED_TABLES = ("records_type", "records_type_revision", "records_record", "records_revision")
"""The global set's tenant-owned tables (design §B)."""


@dataclass
class Tenant:
    name: str
    rtype: RecordType
    record: Record


@asynccontextmanager
async def session_in(db_state: Any, tenant: str) -> AsyncIterator[Any]:
    """A fresh session, bound to ``tenant`` for its whole life; committed on
    a clean exit."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            yield session
            await session.commit()


async def seed_tenant(db_state: Any, name: str) -> Tenant:
    async with session_in(db_state, name) as session:
        rtype = await type_service.create_type(
            session, key="post", label=name, fields_raw=FIELDS, settings=SETTINGS
        )
        record = await record_service.create_record(
            session, rtype, data={"title": name}, settings=SETTINGS
        )
        record.uuid = SAME_UUID
        await session.flush()
    return Tenant(name, rtype, record)


@contextmanager
def statements(db_state: Any) -> Iterator[list[str]]:
    """Every SQL string the engine sends inside the block."""
    seen: list[str] = []

    def record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(" ".join(statement.split()))

    engine = db_state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _target(sql: str) -> str | None:
    """The table an ``UPDATE t …`` or ``DELETE FROM t …`` writes, else ``None``."""
    words = sql.split()
    verb = words[0].upper() if words else ""
    if verb == "UPDATE" and len(words) > 1:
        return words[1].strip('"')
    if verb == "DELETE" and len(words) > 2:
        return words[2].strip('"')
    return None


def owned_writes(seen: list[str]) -> list[str]:
    """The ``UPDATE``/``DELETE`` statements on a tenant-owned table."""
    return [sql for sql in seen if _target(sql) in OWNED_TABLES]


_BY_PRIMARY_KEY = re.compile(r"^\w+\.id = (\?|\$\d+(::\w+)?|%\(\w+\)s)$")
"""``WHERE <table>.id = :p`` and nothing else: the unit of work flushing an object
the session loaded, which it could only have loaded under the bound tenant, and
which the guard's ``before_flush`` refuses unbound. Not a statement records
writes, so not one §E asks a predicate of."""


def unscoped_writes(seen: list[str]) -> list[str]:
    """Those of :func:`owned_writes` whose ``WHERE`` never mentions
    ``tenant_id`` — what §E makes mandatory, so this should be empty — leaving
    out the unit of work's own by-primary-key writes."""
    out = []
    for sql in owned_writes(seen):
        where = sql.split(" WHERE ", 1)[1] if " WHERE " in sql else ""
        if "tenant_id" not in where and not _BY_PRIMARY_KEY.match(where):
            out.append(sql)
    return out
