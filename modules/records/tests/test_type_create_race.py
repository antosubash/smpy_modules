"""#143: two creates of one key must not 500, and a blank label is refused.

``create_type`` checks for the key with a SELECT and inserts afterwards, so
two requests can both pass the check. The unique ``(tenant_id, key)`` index
then refuses the loser — which used to surface as an unhandled
``IntegrityError`` (500) rather than the 409 the sequential duplicate gets.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sm_records.services import types as type_service
from sm_records.services.errors import Conflict, ValidationFailed
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles
from tests.pg_support import USING_POSTGRES


async def test_losing_the_insert_race_is_a_conflict(db, db_state):
    async with db_state.session_factory() as other:
        await type_service.create_type(
            other, key="racer", label="Racer", settings=RecordsSettings()
        )
        await other.commit()

    real_execute = db.execute
    calls = 0

    async def blind_first_select(*args, **kwargs):
        # The duplicate check runs before the other writer's row is visible:
        # answer it with "nothing there", exactly what the loser saw.
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: None))
        return await real_execute(*args, **kwargs)

    db.execute = blind_first_select  # type: ignore[method-assign]
    with pytest.raises(Conflict):
        await type_service.create_type(db, key="racer", label="Racer", settings=RecordsSettings())
    db.execute = real_execute  # type: ignore[method-assign]
    # The savepoint rolled back: the session is still usable.
    assert [t.key for t in await type_service.list_types(db)] == ["racer"]


@pytest.mark.skipif(
    not USING_POSTGRES,
    reason="SQLite's StaticPool shares one connection, so concurrent requests are not "
    "concurrent transactions; set SM_TEST_DATABASE_URL=postgresql+asyncpg://…",
)
async def test_concurrent_creates_give_one_201_and_the_rest_409(client):
    body = {"key": "stampede", "label": "Stampede"}
    resps = await asyncio.gather(
        *(client.post("/api/records/types", json=body, headers=roles(ADMIN)) for _ in range(5))
    )
    statuses = sorted(r.status_code for r in resps)
    assert statuses == [201, 409, 409, 409, 409], statuses


@pytest.mark.parametrize("label", ["", "   ", "\t\n"])
async def test_a_blank_label_is_refused(client, label):
    resp = await client.post(
        "/api/records/types", json={"key": "nolabel", "label": label}, headers=roles(ADMIN)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "label"


async def test_a_blank_label_is_refused_by_the_service(db):
    with pytest.raises(ValidationFailed):
        await type_service.create_type(db, key="nolabel", label=" ", settings=RecordsSettings())


async def test_an_update_cannot_blank_the_label(client):
    made = await client.post(
        "/api/records/types", json={"key": "keepme", "label": "Keep"}, headers=roles(ADMIN)
    )
    assert made.status_code == 201
    resp = await client.put(
        "/api/records/types/keepme",
        json={"expected_version": made.json()["version"], "label": "  "},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
