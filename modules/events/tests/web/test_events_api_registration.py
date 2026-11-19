"""``/api/events/events`` and the registration settings (PR 9): the body, the echo, the refusals."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import registry

from tests.support.events_http import (
    EV,
    OWNER,
    OWNER_PUB,
    VIEWER,
    cast,
    create,
    seed_event,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider

BUILTIN = {
    "mode": "builtin",
    "provider": PROVIDER_ID,
    "target": KNOWN_TARGET,
    "capacity": 40,
    "opens_at_local": "2026-06-01T09:00",
    "closes_at_local": "2026-06-30T17:00",
    "show_seats": True,
    "reminder_minutes": 1440,
}


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, provider())
    yield
    registry.reset_registry()


async def test_round_trip(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, registration=BUILTIN)
    assert made["registration"] == {
        "mode": "builtin",
        "url": None,
        "provider": PROVIDER_ID,
        "target": KNOWN_TARGET,
        "capacity": 40,
        "opens_at_local": "2026-06-01T09:00",
        "closes_at_local": "2026-06-30T17:00",
        "show_seats": True,
        "reminder_minutes": 1440,
        "provider_installed": True,
    }
    got = await client.get(f"{EV}/{made['id']}", headers=OWNER)
    assert got.json()["registration"] == made["registration"]
    assert made["registration_url"] is None


async def test_default_is_none(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    assert made["registration"]["mode"] == "none" and made["registration"]["capacity"] is None


async def test_legacy_url_still_works(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, registration_url="https://x.example/r")
    assert made["registration"]["mode"] == "external"
    assert made["registration"]["url"] == "https://x.example/r"
    assert made["registration_url"] == "https://x.example/r"
    got = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": 1, "registration_url": None},
        headers=OWNER,
    )
    assert got.json()["registration"]["mode"] == "none"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({**BUILTIN, "target": "nope"}, 422, "unknown_registration_target"),
        ({**BUILTIN, "provider": "other:registration"}, 422, "registration_unavailable"),
        ({**BUILTIN, "closes_at_local": "2026-05-01T09:00"}, 422, "invalid_registration"),
        ({**BUILTIN, "reminder_minutes": 7}, 422, "invalid_registration"),
        ({"mode": "external"}, 422, "invalid_registration"),
        ({**BUILTIN, "capacity": 0}, 422, None),  # schema bound: FastAPI's own 422
        ({**BUILTIN, "capacity": 100_001}, 422, None),
        ({**BUILTIN, "surprise": 1}, 422, None),
    ],
)
async def test_refusals(client, body, status, code):
    cal = (await cast(client))["I"]
    got = await client.post(
        EV,
        json={
            "calendar_id": cal,
            "times": {
                "timezone": "Europe/Vienna",
                "start": "2026-07-01T10:00",
                "end": "2026-07-01T11:00",
            },
            "texts": {"en": {"title": "Concert"}},
            "registration": body,
        },
        headers=OWNER,
    )
    assert got.status_code == status, got.text
    if code is not None:
        assert got.json()["code"] == code and set(got.json()) <= {"detail", "code", "field"}


async def test_published_change_needs_publish(client):
    cal = (await cast(client))["I"]
    made = await seed_event(client, cal, status="published")
    body = {"expected_revision": made["revision"], "registration": BUILTIN}
    got = await client.patch(f"{EV}/{made['id']}", json=body, headers=OWNER)
    assert got.status_code == 403 and got.json()["code"] == "publish_required"
    got = await client.patch(f"{EV}/{made['id']}", json=body, headers=OWNER_PUB)
    assert got.status_code == 200, got.text
    assert got.json()["registration"]["capacity"] == 40


async def test_a_viewer_cannot_write_it(client):
    cal = (await cast(client))["I"]
    made = await seed_event(client, cal, status="published")
    got = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": made["revision"], "registration": BUILTIN},
        headers=VIEWER,
    )
    assert got.status_code == 403


async def test_null_registration_is_refused(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    got = await client.patch(
        f"{EV}/{made['id']}", json={"expected_revision": 1, "registration": None}, headers=OWNER
    )
    assert got.status_code == 422


async def test_provider_not_installed_is_shown_and_kept(client, monkeypatch):
    cal = (await cast(client))["I"]
    made = await create(client, cal, registration=BUILTIN)
    install_provider(monkeypatch)  # uninstalled
    got = await client.get(f"{EV}/{made['id']}", headers=OWNER)
    reg = got.json()["registration"]
    assert reg["provider"] == PROVIDER_ID and reg["provider_installed"] is False
    assert reg["capacity"] == 40  # untouched
