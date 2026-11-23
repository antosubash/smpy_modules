"""Who may see an import: its creator, who can currently write its calendar. Nobody else, ever."""

from __future__ import annotations

import pytest
from sm_events.feeds.importing import launch as launch_module
from sm_events.models import Calendar, EventImport, EventImportItem
from sm_events.web.endpoints import imports_api
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.support.access import seed_calendars
from tests.support.app import as_user
from tests.web.test_imports_api import BASE, MGR, M, V, upload

OTHER = as_user("m2", V, M)  # a manager too, but not the creator


@pytest.fixture(autouse=True)
def _eager(monkeypatch):
    monkeypatch.setattr(launch_module, "celery_eager", lambda: True)


@pytest.fixture
async def world(client):
    async with client.db_state.session_factory() as db:
        cals = await seed_calendars(db)
        await db.commit()
    return client, cals


async def _state(client):
    async with client.db_state.session_factory() as db:
        rows = list((await db.execute(select(EventImport))).scalars())
        items = list((await db.execute(select(EventImportItem))).scalars())
    return [(r.id, r.status, r.total) for r in rows], len(items)


CALLS = [
    ("get", "", {}),
    ("get", "/items", {}),
    ("post", "/apply", {"json": {"publish": False}}),
    ("delete", "", {}),
]


async def test_another_user_gets_the_answer_a_missing_import_gets(world):
    client, cals = world
    made = (await upload(client, cals["P"])).json()
    before = await _state(client)
    for method, suffix, extra in CALLS:
        theirs = await getattr(client, method)(
            f"{BASE}/{made['id']}{suffix}", headers=OTHER, **extra
        )
        gone = await getattr(client, method)(f"{BASE}/99999{suffix}", headers=OTHER, **extra)
        assert (theirs.status_code, theirs.json()) == (404, gone.json()), (method, suffix)
        assert theirs.content == gone.content
    assert await _state(client) == before  # nothing was applied, read out or discarded
    assert (await client.get(f"{BASE}/{made['id']}", headers=MGR)).json()["status"] == "staged"


async def test_a_list_holds_only_the_callers_own(world):
    client, cals = world
    mine = (await upload(client, cals["P"])).json()["id"]
    theirs = (await upload(client, cals["I"], headers=OTHER)).json()["id"]
    got = await client.get(BASE, headers=MGR)
    assert [i["id"] for i in got.json()["items"]] == [mine] and got.json()["total"] == 1
    got = await client.get(BASE, headers=OTHER)
    assert [i["id"] for i in got.json()["items"]] == [theirs] and got.json()["total"] == 1


async def test_a_trashed_calendar_hides_the_import_from_its_creator(world):
    client, cals = world
    made = (await upload(client, cals["P"])).json()
    async with client.db_state.session_factory() as db:
        row = (await db.execute(select(Calendar).where(Calendar.id == cals["P"].id))).scalar_one()
        row.is_deleted = True
        await db.commit()
    for method, suffix, extra in CALLS:
        got = await getattr(client, method)(f"{BASE}/{made['id']}{suffix}", headers=MGR, **extra)
        assert got.status_code == 404, (method, suffix)
    assert (await client.get(BASE, headers=MGR)).json() == {"items": [], "total": 0}
    assert (await _state(client))[0][0][1] == "staged"  # left for the janitor


async def test_every_route_goes_through_the_one_helper():
    """A new route that forgets the check fails here."""

    def calls_of(dependant) -> list:
        found = []
        for dep in dependant.dependencies:
            found.append(dep.call)
            found.extend(calls_of(dep))
        return found

    seen = {
        r.name: imports_api.owned_import in calls_of(r.dependant) for r in imports_api.router.routes
    }
    by_id = {name for name, ok in seen.items() if ok}
    assert by_id == {"get_import", "list_items", "apply", "discard"}
    assert set(seen) - by_id == {"list_imports", "upload"}  # the list filters, the upload targets


@pytest.mark.unbound_tenant
async def test_another_tenant_is_the_same_404(multi_client):
    from sm_events.core.tenancy import tenant_scope

    client = multi_client
    cals = {}
    for tenant in ("a", "b"):
        with tenant_scope(tenant):
            async with client.db_state.session_factory() as db:
                cals[tenant] = await seed_calendars(db)
                await db.commit()
    in_a = {**MGR, "X-Test-Tenant": "a"}
    in_b = {**MGR, "X-Test-Tenant": "b"}  # even the same user id, in another tenant
    made = (await upload(client, cals["a"]["P"], headers=in_a)).json()
    for method, suffix, extra in CALLS:
        got = await getattr(client, method)(f"{BASE}/{made['id']}{suffix}", headers=in_b, **extra)
        assert got.status_code == 404
    assert (await client.get(f"{BASE}/{made['id']}", headers=in_a)).status_code == 200
    _ = corpus
