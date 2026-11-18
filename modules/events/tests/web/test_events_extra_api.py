"""``extra`` over HTTP: the 422 shape, the type flags, and an uninstalled type's refusal."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import registry

from tests.support.events_http import EV, OWNER, cast, create, create_json
from tests.support.sources import install_talk


@pytest.fixture(autouse=True)
def talk(monkeypatch):
    install_talk(monkeypatch)
    yield
    registry.reset_registry()


async def test_extra_422_shape(client):
    ids = await cast(client)
    got = await client.post(
        EV, json=create_json(ids["I"], type="acme:talk", extra={"level": "x"}), headers=OWNER
    )
    assert got.status_code == 422
    locs = [e["loc"] for e in got.json()["detail"]]
    assert ["body", "extra", "speaker"] in locs and ["body", "extra", "level"] in locs
    assert "input" not in got.json()["detail"][0]
    big = await client.post(
        EV,
        json=create_json(ids["I"], type="acme:talk", extra={"speaker": "x" * 20_000}),
        headers=OWNER,
    )
    assert (big.status_code, big.json()["code"]) == (422, "extra_too_large")
    unknown = await client.post(
        EV, json=create_json(ids["I"], type="gone:x", extra={}), headers=OWNER
    )
    assert (unknown.status_code, unknown.json()["code"]) == (422, "unknown_type")


async def test_event_out_type_flags_and_round_trip(client):
    ids = await cast(client)
    made = await create(client, ids["I"], type="acme:talk", extra={"speaker": "Ada", "room": "r"})
    assert made["type_installed"] is True and made["type_label_key"] == "acme.types.talk"
    assert made["extra"]["speaker"] == "Ada"
    plain = await create(client, ids["I"])
    assert (plain["type"], plain["type_installed"], plain["type_label_key"]) == (
        "event",
        True,
        "events.types.event",
    )
    patched = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": made["revision"], "extra": {"speaker": "Bo"}},
        headers=OWNER,
    )
    assert patched.status_code == 200 and patched.json()["extra"]["speaker"] == "Bo"
    same_type = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": patched.json()["revision"], "type": "event"},
        headers=OWNER,
    )
    assert (same_type.status_code, same_type.json()["code"]) == (422, "immutable_field")


async def test_uninstalled_type_is_flagged_and_refuses_extra(client):
    ids = await cast(client)
    made = await create(client, ids["I"], type="acme:talk", extra={"speaker": "Ada"})
    registry.reset_registry()  # the plugin is gone from this host
    from sm_events.calendar.plugins import extensions

    extensions._BUILTIN_LOADERS[:] = extensions._BUILTIN_LOADERS[:1]
    shown = (await client.get(f"{EV}/{made['id']}", headers=OWNER)).json()
    assert (shown["type"], shown["type_installed"], shown["type_label_key"]) == (
        "acme:talk",
        False,
        None,
    )
    assert shown["extra"]["speaker"] == "Ada"  # kept, shown read-only
    refused = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": shown["revision"], "extra": {"speaker": "X"}},
        headers=OWNER,
    )
    assert (refused.status_code, refused.json()["code"]) == (422, "type_not_installed")
    ok = await client.patch(
        f"{EV}/{made['id']}",
        json={"expected_revision": shown["revision"], "venue_name": "Hall"},
        headers=OWNER,
    )
    assert ok.status_code == 200 and ok.json()["extra"]["speaker"] == "Ada"
