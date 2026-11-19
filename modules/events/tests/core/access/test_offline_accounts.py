"""``offline_accounts``: many users on one directory read, the same answers one at a time."""

from __future__ import annotations

import pytest
from sm_events.core.access.offline import offline_principal
from starlette.requests import Request

from tests.core.access.test_offline import ROLES, USERS
from tests.support.app import Directory, build_app


def _request(app) -> Request:
    return Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})


@pytest.fixture
async def single():
    app, state = await build_app()
    app.state.user_directory = Directory(USERS, ROLES)
    yield app, state
    await state.engine.dispose()


async def _ask(app, state, user_id):
    async with state.session_factory() as db:
        return await offline_principal(
            app, db, user_id=user_id, tenant_id="default", request=_request(app)
        )


async def test_accounts_in_one_batch(single):
    """Several users at once: one directory call, the same answers as asking one at a time."""
    from sm_events.core.access.offline import offline_accounts

    app, state = single
    directory = app.state.user_directory
    calls = []
    real = directory.get_many

    async def counting(db, ids, **kw):
        calls.append(list(ids))
        return await real(db, ids, **kw)

    directory.get_many = counting
    async with state.session_factory() as db:
        got = await offline_accounts(
            app,
            db,
            user_ids=["viewer", "manager", "off", "idp", "nobody", "ghost", "viewer"],
            tenant_id="default",
            request=_request(app),
        )
    assert len(calls) == 1 and sorted(calls[0]) == sorted(set(calls[0]))
    assert set(got) == {"viewer", "manager", "nobody"}  # inactive, unknown roles and unknown: out
    assert got["viewer"].principal.permissions == frozenset({"events.view"})
    assert got["viewer"].user.email == "viewer@example.com"
    assert got["viewer"].roles == ("viewer",)
    for user in ("viewer", "manager", "nobody"):
        single_one = await _ask(app, state, user)
        assert single_one == got[user].principal
