"""The import API: upload, preview, apply, discard, with rights, limits and tenancy."""

from __future__ import annotations

import pytest
from sm_events.core import constants
from sm_events.feeds.importing import launch as launch_module
from sm_events.models import Event
from sqlalchemy import select

from tests.feeds.importing import corpus
from tests.feeds.importing.runner_support import importer_keeps_stored_rights
from tests.feeds.importing.staging_support import make_import
from tests.support.access import seed_calendars
from tests.support.app import as_user

V, E, M, P = "events.view", "events.edit", "events.manage", "events.publish"
BASE = "/api/events/imports"
MGR, PUB, EDITOR = as_user("m", V, M), as_user("p", V, M, P), as_user("e", V, E)
SECRET_MAIL = "mailto:jane@example.com"


@pytest.fixture(autouse=True)
def _eager(monkeypatch):
    """Celery's eager mode: the launch runs its slices on the request's own loop."""
    monkeypatch.setattr(launch_module, "celery_eager", lambda: True)
    importer_keeps_stored_rights(monkeypatch)


@pytest.fixture
async def world(client):
    async with client.db_state.session_factory() as db:
        cals = await seed_calendars(db)
        await db.commit()
    return client, cals


async def upload(client, cal, data: bytes | None = None, *, headers=MGR, name="cal.ics"):
    return await client.post(
        BASE,
        data={"calendar_id": str(cal.id)},
        files={"file": (name, corpus.simple(3) if data is None else data, "text/calendar")},
        headers=headers,
    )


async def events_of(client) -> list[Event]:
    async with client.db_state.session_factory() as db:
        return list((await db.execute(select(Event).order_by(Event.uid))).scalars())


async def test_upload_preview_apply_eager(world):
    client, cals = world
    made = await upload(client, cals["P"])
    assert made.status_code == 202, made.text
    body = made.json()
    assert (body["status"], body["total"], body["calendar"]["name"]) == ("staged", 3, "private")
    assert body["counts"] == {"new": 3, "update": 0, "skip": 0}
    assert (await client.get(f"{BASE}/{body['id']}", headers=MGR)).json()["status"] == "staged"
    items = await client.get(f"{BASE}/{body['id']}/items", headers=MGR)
    assert items.status_code == 200
    page = items.json()
    assert page["total"] == 3 and [i["verdict"] for i in page["items"]] == ["new"] * 3
    assert [i["uid"] for i in page["items"]] == ["u0@x", "u1@x", "u2@x"]
    assert {(i["timezone"], i["local_start"]) for i in page["items"]} == {
        ("UTC", "2026-07-01T10:00")
    }
    assert set(page["items"][0]) == {
        "seq", "uid", "verdict", "reason", "notes", "title", "starts_at", "timezone", "local_start",
        "all_day", "recurring", "outcome", "outcome_code", "event_id",
    }  # fmt: skip
    assert await events_of(client) == []  # a preview writes nothing
    applied = await client.post(f"{BASE}/{body['id']}/apply", json={"publish": False}, headers=MGR)
    assert applied.status_code == 202, applied.text
    done = (await client.get(f"{BASE}/{body['id']}", headers=MGR)).json()
    assert (done["status"], done["created"], done["processed"]) == ("done", 3, 3)
    assert done["finished_at"] is not None
    events = await events_of(client)
    assert [(e.uid, e.status) for e in events] == [(f"u{n}@x", "draft") for n in range(3)]
    after = (await client.get(f"{BASE}/{body['id']}/items", headers=MGR)).json()["items"]
    assert [i["outcome"] for i in after] == ["created"] * 3 and all(i["event_id"] for i in after)
    filtered = await client.get(
        f"{BASE}/{body['id']}/items?outcome=created&page_size=2", headers=MGR
    )
    assert (len(filtered.json()["items"]), filtered.json()["total"]) == (2, 3)


async def test_list_is_newest_first_and_paged(world):
    client, cals = world
    ids = [(await upload(client, cals["P"], name=f"{n}.ics")).json()["id"] for n in range(3)]
    got = await client.get(BASE, headers=MGR)
    assert [i["id"] for i in got.json()["items"]] == sorted(ids, reverse=True)
    assert got.json()["total"] == 3
    page = await client.get(BASE, params={"page": 2, "page_size": 2}, headers=MGR)
    assert [i["id"] for i in page.json()["items"]] == [min(ids)]
    assert (await client.get(BASE, params={"page": 0}, headers=MGR)).status_code == 422


async def test_publish_needs_permission(world):
    client, cals = world
    made = (await upload(client, cals["P"])).json()
    refused = await client.post(f"{BASE}/{made['id']}/apply", json={"publish": True}, headers=MGR)
    assert (refused.status_code, refused.json()["code"]) == (403, "publish_required")
    assert (await client.get(f"{BASE}/{made['id']}", headers=MGR)).json()["status"] == "staged"
    mine = (await upload(client, cals["I"], headers=PUB)).json()  # the publisher's own import
    ok = await client.post(f"{BASE}/{mine['id']}/apply", json={"publish": True}, headers=PUB)
    assert ok.status_code == 202
    assert {e.status for e in await events_of(client)} == {"published"}


async def test_apply_twice_conflicts(world):
    client, cals = world
    made = (await upload(client, cals["P"])).json()
    await client.post(f"{BASE}/{made['id']}/apply", json={"publish": False}, headers=MGR)
    again = await client.post(f"{BASE}/{made['id']}/apply", json={"publish": False}, headers=MGR)
    assert (again.status_code, again.json()["code"]) == (409, "import_state")
    assert len(await events_of(client)) == 3


async def test_discard(world):
    client, cals = world
    made = (await upload(client, cals["P"])).json()
    assert (await client.delete(f"{BASE}/{made['id']}", headers=MGR)).status_code == 204
    assert (await client.get(f"{BASE}/{made['id']}", headers=MGR)).status_code == 404
    assert (await client.delete(f"{BASE}/{made['id']}", headers=MGR)).status_code == 404
    async with client.db_state.session_factory() as db:
        from sm_events.models import EventImportItem

        assert (await db.execute(select(EventImportItem))).scalars().all() == []
        busy = await make_import(db, cals["P"], status="running")
        await db.commit()
    got = await client.delete(f"{BASE}/{busy.id}", headers=MGR)  # not while a worker holds it
    assert (got.status_code, got.json()["code"]) == (409, "import_state")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("get", "/1"),
        ("get", "/1/items"),
        ("post", "/1/apply"),
        ("delete", "/1"),
    ],
)
async def test_needs_manage(world, method, path):
    client, _cals = world
    kwargs = {"json": {"publish": False}} if path.endswith("apply") else {}
    got = await getattr(client, method)(f"{BASE}{path}", headers=EDITOR, **kwargs)
    assert got.status_code == 403
    assert (await getattr(client, method)(f"{BASE}{path}", **kwargs)).status_code in (401, 403)


async def test_upload_needs_manage(world):
    client, cals = world
    assert (await upload(client, cals["P"], headers=EDITOR)).status_code == 403
    assert await events_of(client) == []


async def test_no_source_or_payload_in_responses(world):
    client, cals = world
    data = corpus.calendar(
        *corpus.vevent(
            "p@x", f"ATTENDEE;CN=Jane:{SECRET_MAIL}", "ORGANIZER:mailto:boss@example.com"
        )
    )
    made = await upload(client, cals["P"], data)
    import_id = made.json()["id"]
    await client.post(f"{BASE}/{import_id}/apply", json={"publish": False}, headers=MGR)
    raw = b"".join(
        [
            made.content,
            (await client.get(BASE, headers=MGR)).content,
            (await client.get(f"{BASE}/{import_id}", headers=MGR)).content,
            (await client.get(f"{BASE}/{import_id}/items", headers=MGR)).content,
        ]
    )
    for banned in (b'"source"', b'"payload"', b"BEGIN:VCALENDAR", b"jane", b"boss", b"example.com"):
        assert banned not in raw, banned
    assert made.json()["dropped"] == {"ATTENDEE": 1, "ORGANIZER": 1}


async def test_error_envelopes(world):
    client, cals = world
    png = await upload(client, cals["P"], b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    assert (png.status_code, png.json()["code"], set(png.json())) == (
        422,
        "ics_invalid",
        {"detail", "code"},
    )
    client.app.state.sm_events.settings.import_max_bytes = 1  # clamped up to the floor
    big = await upload(client, cals["P"], corpus.long_line(constants.IMPORT_MIN_BYTES + 10_000))
    client.app.state.sm_events.settings.import_max_bytes = constants.IMPORT_DEFAULT_BYTES
    assert (big.status_code, big.json()["code"]) == (413, "import_too_large")
    missing = await client.post(
        BASE,
        data={"calendar_id": "00000000-0000-0000-0000-000000000000"},
        files={"file": ("a.ics", corpus.simple(), "text/calendar")},
        headers=MGR,
    )
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")
    assert (await client.get(f"{BASE}/99999", headers=MGR)).json()["code"] == "not_found"
    real = (await upload(client, cals["P"], name="real.ics")).json()["id"]
    assert (await client.get(f"{BASE}/{real}/items?verdict=bogus", headers=MGR)).status_code == 422
    assert (await client.get(f"{BASE}/{real}/items?page_size=101", headers=MGR)).status_code == 422
    for _ in range(constants.IMPORT_ACTIVE_MAX - 1):
        assert (await upload(client, cals["P"])).status_code == 202
    busy = await upload(client, cals["P"])
    assert (busy.status_code, busy.json()["code"]) == (409, "import_busy")


async def test_a_failed_file_is_an_answer_not_an_error(world):
    client, cals = world
    got = await upload(client, cals["P"], corpus.invalid_utf8())
    assert got.status_code == 202
    assert (got.json()["status"], got.json()["error_code"]) == ("failed", "ics_encoding")
    assert (await client.get(f"{BASE}/{got.json()['id']}/items", headers=MGR)).json()["total"] == 0


async def test_the_filename_is_a_safe_name(world):
    client, cals = world
    got = await upload(client, cals["P"], name="../../etc/passwd.ics")
    assert got.json()["filename"] == "passwd.ics"
