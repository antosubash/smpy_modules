"""A new image on an event must be one the site may show; stored data stays as it is."""

from __future__ import annotations

import uuid

from sm_events.models import Event
from sqlalchemy import update

from tests.support.events_http import EV, OWNER, cast, create, run

OFF = "https://cdn.example.net/studio.jpg"


async def test_a_new_off_site_image_is_refused_with_a_field_error(client):
    cal = (await cast(client))["I"]
    got = await client.post(
        EV,
        json={
            "calendar_id": cal,
            "times": {"timezone": "UTC", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
            "texts": {"en": {"title": "Open day"}},
            "image": OFF,
        },
        headers=OWNER,
    )
    assert got.status_code == 422
    assert got.json()["code"] == "image_off_site" and got.json()["field"] == "image"


async def test_a_site_path_and_an_own_origin_address_are_accepted(client):
    cal = (await cast(client))["I"]
    for image in ("/media/studio.jpg", "http://test/media/studio.jpg"):
        made = await create(client, cal, image=image)
        assert made["image"] == image


async def test_a_patch_refuses_a_new_off_site_value_but_keeps_what_is_stored(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    event_id = made["id"]

    async def store(db):
        await db.execute(update(Event).where(Event.id == uuid.UUID(event_id)).values(image=OFF))

    await run(client, store)
    current = (await client.get(f"{EV}/{event_id}", headers=OWNER)).json()
    # What the editor sends back unchanged: accepted, as stored data always was.
    same = await client.patch(
        f"{EV}/{event_id}",
        json={"expected_revision": current["revision"], "image": OFF, "cancelled": True},
        headers=OWNER,
    )
    assert same.status_code == 200, same.text
    other = await client.patch(
        f"{EV}/{event_id}",
        json={"expected_revision": same.json()["revision"], "image": "https://other.example/x.jpg"},
        headers=OWNER,
    )
    assert other.status_code == 422 and other.json()["code"] == "image_off_site"
    cleared = await client.patch(
        f"{EV}/{event_id}",
        json={"expected_revision": same.json()["revision"], "image": None},
        headers=OWNER,
    )
    assert cleared.status_code == 200 and cleared.json()["image"] is None
