"""The reminders API: following, availability, "my reminders", and that it is all one's own."""

from __future__ import annotations

import uuid

import pytest
from simple_module_core.mail import reset_mail_sender
from sm_events.models import EventFollow
from sm_events.reminders import limits
from sqlalchemy import func, select

from tests.reminders.support import make_ready, seed_http
from tests.support.app import as_user

V, E, M = "events.view", "events.edit", "events.manage"
BASE = "/api/events"
U, Z, MGR = as_user("u", V), as_user("z", V), as_user("m", V, M)
SV, SE = as_user("sv", V), as_user("se", V)
ALL_LEADS = list(limits.REMINDER_LEADS)


@pytest.fixture(autouse=True)
def _clean_mail():
    reset_mail_sender()
    yield
    reset_mail_sender()


@pytest.fixture
async def world(client, monkeypatch):
    make_ready(client.app, monkeypatch)
    return client, await seed_http(client)


def follow_url(event_id: str) -> str:
    return f"{BASE}/events/{event_id}/follow"


async def _count(client, user: str | None = None) -> int:
    async with client.db_state.session_factory() as db:
        stmt = select(func.count()).select_from(EventFollow)
        if user:
            stmt = stmt.where(EventFollow.user_id == user)
        return (await db.execute(stmt)).scalar_one()


async def test_round_trip(world):
    client, ids = world
    url = follow_url(ids["pub"]["I"])
    got = await client.get(url, headers=U)
    assert got.status_code == 200, got.text
    assert got.json() == {
        "leads": [], "defaults": [60], "next_due": {}, "deliverable": True, "code": None,
    }  # fmt: skip
    put = await client.put(url, json={"leads": [60, 15]}, headers=U)
    assert put.status_code == 200, put.text
    assert put.json() == {
        "leads": [15, 60],
        "defaults": [60],
        "next_due": {"15": None, "60": None},
        "deliverable": True,
        "code": None,
    }
    assert (await client.get(url, headers=U)).json()["leads"] == [15, 60]
    assert await _count(client, "u") == 2  # committed, not just flushed
    assert (await client.put(url, json={"leads": [1440]}, headers=U)).json()["leads"] == [1440]
    assert (await client.put(url, json={"leads": []}, headers=U)).json()["leads"] == []
    assert await _count(client) == 0
    assert (await client.delete(url, headers=U)).status_code == 204
    await client.put(url, json={"leads": [60]}, headers=U)
    assert (await client.delete(url, headers=U)).status_code == 204
    assert (await client.delete(url, headers=U)).status_code == 204  # idempotent
    assert await _count(client) == 0  # a DELETE commits too


async def test_unavailable_blocks_writes_not_reads(world):
    client, ids = world
    url = follow_url(ids["pub"]["I"])
    assert (await client.put(url, json={"leads": [60]}, headers=U)).status_code == 200
    client.app.state.sm_events.settings.reminders_enabled = False
    put = await client.put(url, json={"leads": [15]}, headers=U)
    assert (put.status_code, put.json()["code"]) == (503, "reminders_unavailable")
    assert set(put.json()) == {"detail", "code"}
    assert (await client.get(url, headers=U)).status_code == 200
    assert (await client.get(f"{BASE}/reminders/mine", headers=U)).status_code == 200
    # Stopping is never refused: nobody is stuck with a follow they cannot remove.
    assert (await client.put(url, json={"leads": []}, headers=U)).status_code == 200
    assert (await client.delete(url, headers=U)).status_code == 204
    assert await _count(client) == 0


async def test_status_and_reason_only_for_managers(world):
    client, _ = world
    got = (await client.get(f"{BASE}/reminders/status", headers=U)).json()
    assert got == {"available": True, "leads": ALL_LEADS}
    client.app.state.sm.settings.public_base_url = ""
    mine = (await client.get(f"{BASE}/reminders/status", headers=U)).json()
    assert mine == {"available": False, "leads": ALL_LEADS}  # no ``reason`` key at all
    managers = (await client.get(f"{BASE}/reminders/status", headers=MGR)).json()
    assert managers == {"available": False, "reason": "no_public_base_url", "leads": ALL_LEADS}
    assert (await client.get(f"{BASE}/reminders/status")).status_code == 401
    assert (await client.get(f"{BASE}/reminders/status", headers=as_user("n"))).status_code == 403


async def test_invisible_404_everywhere(world):
    """An event the caller cannot see and one that does not exist answer byte for byte alike."""
    client, ids = world
    hidden, missing = follow_url(ids["pub"]["P"]), follow_url(str(uuid.uuid4()))
    for method, body in (("get", None), ("put", {"leads": [60]}), ("delete", None)):
        kwargs = {"json": body} if body is not None else {}
        a = await getattr(client, method)(hidden, headers=Z, **kwargs)
        b = await getattr(client, method)(missing, headers=Z, **kwargs)
        assert (a.status_code, a.content) == (b.status_code, b.content), method
        assert a.status_code == 404 and a.json()["code"] == "not_found"
    # Trashed and draft-for-a-viewer too.
    for event_id in (ids["draft"]["I"], ids["draft"]["P"]):
        assert (
            await client.put(follow_url(event_id), json={"leads": [60]}, headers=Z)
        ).status_code == 404
    assert await _count(client) == 0


async def test_error_envelope(world):
    client, ids = world
    url = follow_url(ids["pub"]["I"])
    bad = await client.put(url, json={"leads": [30]}, headers=U)
    draft = await client.put(follow_url(ids["draft"]["P"]), json={"leads": [60]}, headers=SE)
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_lead")
    assert (draft.status_code, draft.json()["code"]) == (409, "not_published")
    async with client.db_state.session_factory() as db:
        for i in range(limits.FOLLOWS_PER_USER):
            from sm_events.models import Calendar

            from tests.reminders.support import follow_row, published

            cal = (
                await db.execute(select(Calendar).where(Calendar.slug == "internal"))
            ).scalar_one()
            db.add(follow_row(await published(db, cal, title=f"F{i}")))
        await db.commit()
    full = await client.put(url, json={"leads": [60]}, headers=U)
    assert (full.status_code, full.json()["code"]) == (409, "follow_limit")
    for got in (bad, draft, full):
        assert set(got.json()) == {"detail", "code"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"leads": "60"},
        {"leads": [True]},
        {"leads": ["60"]},
        {"leads": [60.5]},
        {"leads": [60] * 17},
    ],
)
async def test_malformed_bodies_are_422(world, body):
    client, ids = world
    got = await client.put(follow_url(ids["pub"]["I"]), json=body, headers=U)
    assert got.status_code == 422
    assert await _count(client) == 0


async def test_bad_event_id_is_422(world):
    client, _ = world
    assert (await client.get(follow_url("not-a-uuid"), headers=U)).status_code == 422


async def test_writes_need_csrf(csrf_client, monkeypatch):
    make_ready(csrf_client.app, monkeypatch)
    ids = await seed_http(csrf_client)
    url = follow_url(ids["pub"]["I"])
    assert (await csrf_client.put(url, json={"leads": [60]}, headers=U)).status_code == 403
    assert (await csrf_client.delete(url, headers=U)).status_code == 403
    token = (await csrf_client.get("/token")).json()["token"]
    ok = await csrf_client.put(url, json={"leads": [60]}, headers={**U, "X-CSRF-Token": token})
    assert ok.status_code == 200
    gone = await csrf_client.delete(url, headers={**U, "X-CSRF-Token": token})
    assert gone.status_code == 204


async def test_delivery_needs_manage(world):
    client, _ = world
    assert (await client.get(f"{BASE}/reminders/delivery", headers=U)).status_code == 403
    got = await client.get(f"{BASE}/reminders/delivery", headers=MGR)
    assert got.status_code == 200, got.text
    assert got.json() == {
        "enabled": True,
        "available": True,
        "reason": None,
        "defaults": [60],
        "window_days": 30,
        "counts": {"sent": 0, "failed": {}, "unfinished": 0},
    }
    client.app.state.sm_events.settings.reminders_enabled = False
    down = (await client.get(f"{BASE}/reminders/delivery", headers=MGR)).json()
    assert (down["enabled"], down["available"], down["reason"]) == (False, False, "disabled")
