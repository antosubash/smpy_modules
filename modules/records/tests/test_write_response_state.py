"""A write must leave the row's instance whole enough to answer with.

The endpoints build their responses *synchronously*, after the last ``await``:
``record_read(rtype, updated)`` reads a dozen attributes off the instance the
service just wrote. If any of those attributes is **expired**, reading it is a
lazy load — a database round trip attempted from outside the async greenlet —
and SQLAlchemy raises ``MissingGreenlet``. The request then 500s with the
write already done and the client never learning the new version, which is how
this was found: 5/5 on the Postgres demo host, on saves of several fields at
once, while an isolated single-field save came back 200.

The expiry came from ``guarded_bump``. ``AuditMixin`` declares ``updated_at``
``onupdate=func.now()``, so every ``UPDATE`` that does not name the column
carries a value the ORM cannot know and answers by expiring the attribute.
Whether the 500 followed was luck: the framework's ``before_flush`` audit
listener assigns ``updated_at`` on any row it considers modified, which
un-expires it — and a save whose columns all keep their values is not
modified, so nothing put it back.

So the regression is pinned where the expiry was, not where it blew up: after
``guarded_bump`` the instance must have **nothing** unloaded. The HTTP tests
below are the behaviour that depends on it.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sm_records.models import Record, RecordType
from sm_records.services._common import guarded_bump
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from tests.app_harness import ADMIN, roles
from tests.app_harness import field as _field
from tests.pg_support import USING_POSTGRES, make_db_state

pytestmark = pytest.mark.skipif(
    not USING_POSTGRES,
    reason="the 500 was found on Postgres and the asyncpg driver is what makes an "
    "off-greenlet lazy load fatal; set RECORDS_TEST_URL=postgresql+asyncpg://…",
)

SETTINGS = RecordsSettings()


@pytest_asyncio.fixture
async def pg_state() -> Any:
    state = await make_db_state()
    yield state
    await state.engine.dispose()


async def test_the_version_bump_leaves_no_attribute_expired(pg_state):
    """The root cause, directly. Before the fix this reported
    ``unloaded: ['updated_at']`` — one lazy load away from a 500 in any code
    path that reads the column without awaiting."""
    async with pg_state.session_factory() as session:
        rtype = RecordType(
            key="gadget",
            label="Gadget",
            label_plural="Gadgets",
            fields=[_field("name", "text")],
            display_field="name",
        )
        session.add(rtype)
        await session.flush()
        record = await create_record(session, rtype, data={"name": "one"}, settings=SETTINGS)
        await session.commit()
        row_id = int(record.id)

    async with pg_state.session_factory() as session:
        record = (
            (await session.execute(select(Record).where(Record.id == row_id))).scalars().first()
        )
        before = record.updated_at
        assert await guarded_bump(session, Record, row_id, record.version) is True
        assert sa_inspect(record).unloaded == set()
        assert record.version == 2
        assert record.updated_at is not None and record.updated_at != before


@pytest.fixture
def payload() -> dict:
    return {
        "name": "Acme",
        "description": "the long one",
        "website": "https://acme.example",
        "is_public": False,
    }


async def _company(client) -> dict:
    body = {
        "key": "company",
        "label": "Company",
        "fields": [
            _field("name", "text", unique=True),
            _field("description", "longtext", indexed=False),
            _field("website", "url"),
            _field("is_public", "boolean"),
            _field("owner", "relation", target_type="company"),
        ],
        "display_field": "name",
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_multi_field_save_answers_200_with_the_new_version(client, payload):
    """The QA's reproduction, end to end: several fields of different kinds —
    text, longtext, url, boolean — on a type that also has a ``unique`` field
    and an indexed relation, all changed in one save."""
    await _company(client)
    api = "/api/records/types/company/records"
    created = (await client.post(api, json={"data": payload}, headers=roles(ADMIN))).json()
    linked = (
        await client.post(api, json={"data": {**payload, "name": "Other"}}, headers=roles(ADMIN))
    ).json()

    updated = await client.put(
        f"{api}/{created['uuid']}",
        json={
            "expected_version": created["version"],
            "data": {
                "name": "Acme Two",
                "description": "a different long one",
                "website": "https://acme.test",
                "is_public": True,
                "owner": {"type": "company", "uuid": linked["uuid"]},
            },
        },
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["version"] == created["version"] + 1
    assert body["updated_at"] is not None
    assert body["data"]["name"] == "Acme Two"
    assert body["data"]["is_public"] is True


async def test_saving_a_form_unchanged_answers_200_too(client, payload):
    """The shape that made it fire: every column keeps its value, so the audit
    listener does not consider the row modified and never re-assigns
    ``updated_at`` — leaving the expiry ``guarded_bump`` caused in place for
    the response to trip over."""
    await _company(client)
    api = "/api/records/types/company/records"
    created = (await client.post(api, json={"data": payload}, headers=roles(ADMIN))).json()

    again = await client.put(
        f"{api}/{created['uuid']}",
        json={"expected_version": created["version"], "data": payload},
        headers=roles(ADMIN),
    )
    assert again.status_code == 200, again.text
    assert again.json()["version"] == created["version"] + 1
    assert again.json()["updated_at"] is not None
