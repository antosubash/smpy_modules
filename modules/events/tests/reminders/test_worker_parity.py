"""The gate: the worker's principal never grants more than a request principal would.

Walked over users x calendars x event states. Where the two differ it is the worker that holds
less, and only for a right a worker cannot read (the membership role, upstream #1005)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from simple_module_core.resources import ResourcePrincipal
from simple_module_hosting.permissions import resolve_principal_permissions
from sm_events.core.access.events import visible_events
from sm_events.core.access.offline import OfflineUser, offline_accounts
from sm_events.models import Event
from sm_events.reminders import worker_app
from sm_events.reminders.runtime import web_runtime
from sqlalchemy import select
from starlette.requests import Request

from tests.reminders.support import published, world
from tests.support.app import Directory, build_app
from tests.support.calendars import seed_event
from tests.support.tokens import ROLES, USERS

MEMBER_ROLE = "tenant:member"
USERS_ALL = {
    **USERS,
    "tr": ("tr@example.com", "Role only", True),  # holds events.view only through the membership
    "idp": ("idp@example.com", "Idp", True),  # roles live in the identity provider
    "off": ("off@example.com", "Off", False),
}
ROLES_ALL = {**ROLES, "tr": (), "idp": None, "off": ("viewer",)}
EQUAL = {"o", "sv", "se", "v", "m", "e", "x"}
"""Users whose roles already give everything the membership role gives."""
NARROWER = {"a", "tr"}
"""Users the request principal holds more for: the right comes only from the membership role."""


@pytest.fixture
async def host(monkeypatch):
    app, state = await build_app()
    app.state.user_directory = Directory(dict(USERS_ALL), dict(ROLES_ALL))
    app.state.sm.permissions.map_role(MEMBER_ROLE, ["events.view"])
    monkeypatch.setattr(worker_app, "_settings", lambda: object())
    monkeypatch.setattr(worker_app, "_create_app", lambda s: app)
    monkeypatch.setattr(worker_app, "_db_factory", lambda: state.session_factory)
    worker_app.reset_worker_app()
    async with state.session_factory() as db:
        yield app, db
    worker_app.reset_worker_app()
    await state.engine.dispose()


async def _states(db):
    """Every calendar x every event state."""
    cals = await world(db)
    cals["G"] = cals["U"].__class__(slug="gone", name="gone", owner_id="o", visibility="public")
    db.add(cals["G"])
    await db.flush()
    out = {}
    for key, cal in cals.items():
        out[(key, "published")] = await published(db, cal, title=f"{key}-pub")
        out[(key, "cancelled")] = await published(db, cal, title=f"{key}-x", cancelled=True)
        out[(key, "draft")] = await seed_event(db, cal, status="draft", title=f"{key}-d")
        out[(key, "review")] = await seed_event(db, cal, status="in_review", title=f"{key}-r")
        out[(key, "scheduled")] = await seed_event(
            db, cal, status="draft", title=f"{key}-s", publish_at=datetime(2030, 1, 1, tzinfo=UTC)
        )
        out[(key, "trashed")] = await published(db, cal, title=f"{key}-t")
        await db.delete(out[(key, "trashed")])
    await db.flush()
    await db.delete(cals["G"])
    await db.flush()
    return out


async def _request_principal(app, user_id: str) -> ResourcePrincipal:
    """What a live request for this user holds: the directory roles AND the membership role."""
    record = USERS_ALL[user_id]
    roles = (*(ROLES_ALL[user_id] or ()), MEMBER_ROLE) if record[2] else ()
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})
    held = await resolve_principal_permissions(
        request,
        OfflineUser(id=user_id, roles=roles, tenant_id="default"),
        app.state.sm.permissions,
    )
    return ResourcePrincipal(user_id=user_id, permissions=frozenset(held))


async def _seen(db, who, *, unpublished: bool) -> set:
    rows = await db.execute(visible_events(who, include_unpublished=unpublished))
    return {e.id for e in rows.scalars()}


async def test_worker_runtime_parity(host):
    app, db = host
    await _states(db)
    runtime = await worker_app.worker_runtime(db)
    assert runtime is not None
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})
    accounts = await offline_accounts(
        app, db, user_ids=list(USERS_ALL), tenant_id="default", request=request
    )
    for user_id in USERS_ALL:
        account = accounts.get(user_id)
        if account is None:  # nothing established: nothing granted
            assert user_id in {"idp", "off"}, user_id
            continue
        theirs = await _request_principal(app, user_id)
        worker = account.principal
        assert worker.permissions <= theirs.permissions, user_id
        for unpublished in (False, True):
            got, want = (
                await _seen(db, worker, unpublished=unpublished),
                await _seen(db, theirs, unpublished=unpublished),
            )
            assert got <= want, (user_id, unpublished)
            if user_id in EQUAL:
                assert got == want, (user_id, unpublished)
        if user_id in EQUAL:
            assert worker.permissions == theirs.permissions, user_id
        if user_id in NARROWER:
            assert worker.permissions < theirs.permissions, user_id  # the documented limit
            assert not worker.has("events.view")  # so ``eligible`` says no_view


async def test_the_runtime_resolves_the_same_principals(host):
    app, db = host
    await _states(db)
    runtime = await worker_app.worker_runtime(db)
    web = await web_runtime(app).recipients(db, tenant_id="default", user_ids=list(USERS_ALL))
    headless = await runtime.recipients(db, tenant_id="default", user_ids=list(USERS_ALL))
    assert {u: r.principal for u, r in headless.items()} == {u: r.principal for u, r in web.items()}
    assert set(headless) == set(USERS_ALL) - {"idp", "off"}


async def test_nothing_is_granted_that_cannot_be_established(host):
    """Unknown roles, an inactive account, an unknown id, a missing registry: all absent."""
    app, db = host
    runtime = await worker_app.worker_runtime(db)
    got = await runtime.recipients(db, tenant_id="default", user_ids=["idp", "off", "ghost", "tr"])
    assert set(got) == {"tr"} and "events.view" not in got["tr"].principal.permissions
    app.state.sm.permissions = None
    assert await runtime.recipients(db, tenant_id="default", user_ids=["v"]) == {}


async def test_the_whole_cast_is_present(host):
    _, db = host
    states = await _states(db)
    assert len(states) == 4 * 6  # 3 calendars + the trashed one, six states each
    assert (await db.execute(select(Event))).scalars().first() is not None
