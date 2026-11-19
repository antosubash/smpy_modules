"""Told, never silent: a follow whose reminders the worker could not send says so."""

from __future__ import annotations

import pytest
from simple_module_core.mail import reset_mail_sender
from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventFollow
from sqlalchemy import func, select

from tests.reminders.support import make_ready, seed_http
from tests.support.app import Directory, as_user
from tests.support.tokens import install_members

V = "events.view"
BASE = "/api/events"
CODE = "reminders_no_access"


@pytest.fixture(autouse=True)
def _clean_mail():
    reset_mail_sender()
    yield
    reset_mail_sender()


def follow_url(event_id: str) -> str:
    return f"{BASE}/events/{event_id}/follow"


async def _stored(client, user: str) -> int:
    async with client.db_state.session_factory() as db:
        stmt = select(func.count()).select_from(EventFollow).where(EventFollow.user_id == user)
        return (await db.execute(stmt)).scalar_one()


async def test_a_directly_granted_user_is_not_told(client, monkeypatch):
    make_ready(client.app, monkeypatch)
    ids = await seed_http(client)
    url = follow_url(ids["pub"]["U"])
    put = await client.put(url, json={"leads": [60]}, headers=as_user("u", V))
    assert put.status_code == 200
    assert (put.json()["deliverable"], put.json()["code"]) == (True, None)
    got = (await client.get(url, headers=as_user("u", V))).json()
    assert (got["deliverable"], got["code"]) == (True, None)
    mine = (await client.get(f"{BASE}/reminders/mine", headers=as_user("u", V))).json()
    assert [i["deliverable"] for i in mine["items"]] == [True]


@pytest.mark.unbound_tenant
async def test_a_role_only_member_on_a_multi_tenant_host_is_told(multi_client, monkeypatch):
    """The request principal holds ``events.view`` through the membership role; a worker cannot
    read that, so no reminder would ever come. The follow is stored, and everyone is told."""
    client = multi_client
    make_ready(client.app, monkeypatch)
    client.app.state.user_directory = Directory(
        {"tr": ("tr@example.com", "Tr", True), "ok": ("ok@example.com", "Ok", True)},
        {"tr": (), "ok": ("viewer",)},
    )
    install_members(client.app, {"a": {"tr", "ok"}})
    ids = await seed_http(client, "a")
    url = follow_url(ids["pub"]["U"])
    told = as_user("tr", V, tenant="a")
    put = await client.put(url, json={"leads": [60]}, headers=told)
    assert put.status_code == 200, put.text
    body = put.json()
    assert (body["deliverable"], body["code"]) == (False, CODE) and body["leads"] == [60]
    with tenant_scope("a"):
        assert await _stored(client, "tr") == 1  # still stored: a re-grant resumes it
    got = (await client.get(url, headers=told)).json()
    assert (got["deliverable"], got["code"]) == (False, CODE)
    mine = (await client.get(f"{BASE}/reminders/mine", headers=told)).json()
    assert [i["deliverable"] for i in mine["items"]] == [False]
    # The same host, a user whose role gives the right directly: not told.
    fine = as_user("ok", V, tenant="a")
    ok = (await client.put(url, json={"leads": [60]}, headers=fine)).json()
    assert (ok["deliverable"], ok["code"]) == (True, None)


@pytest.mark.unbound_tenant
@pytest.mark.parametrize("case", ["no_directory_record", "inactive", "not_a_member", "idp_roles"])
async def test_every_way_a_worker_cannot_tell_is_told(multi_client, monkeypatch, case):
    client = multi_client
    make_ready(client.app, monkeypatch)
    users = {"x": ("x@example.com", "X", case != "inactive")}
    roles = {"x": None if case == "idp_roles" else ("viewer",)}
    if case == "no_directory_record":
        users = {}
    client.app.state.user_directory = Directory(users, roles)
    install_members(client.app, {"a": set() if case == "not_a_member" else {"x"}})
    ids = await seed_http(client, "a")
    put = await client.put(
        follow_url(ids["pub"]["U"]), json={"leads": [60]}, headers=as_user("x", V, tenant="a")
    )
    assert put.status_code == 200 and (put.json()["deliverable"], put.json()["code"]) == (
        False,
        CODE,
    )


async def test_stopping_is_always_possible_and_untold_when_nothing_is_followed(client, monkeypatch):
    make_ready(client.app, monkeypatch)
    ids = await seed_http(client)
    url = follow_url(ids["pub"]["U"])
    await client.put(url, json={"leads": [60]}, headers=as_user("u", V))
    got = await client.put(url, json={"leads": []}, headers=as_user("u", V))
    assert got.status_code == 200 and got.json()["leads"] == []
