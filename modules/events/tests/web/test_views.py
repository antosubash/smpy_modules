"""Console routing, permissions and initial props against the real Inertia adapter."""

import pytest
from fastapi.templating import Jinja2Templates
from simple_module_inertia import InertiaConfig, inertia_dependency_factory

from tests.support.app import as_user
from tests.support.events_http import STRANGER, VIEWER, cast, seed_event


@pytest.fixture(autouse=True)
def inertia(events_app):
    app, _ = events_app
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(templates=Jinja2Templates(directory="."), version="test")
    )


def headers(*perms):
    return {**as_user("owner", *perms), "X-Inertia": "true", "X-Inertia-Version": "test"}


async def test_root_redirects_to_calendars(client):
    response = await client.get("/admin/events/", headers=headers("events.view"))
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/events/calendars"


@pytest.mark.parametrize(
    "perms,flags",
    [
        (("events.view",), (False, False)),
        (("events.view", "events.edit", "events.manage"), (True, True)),
    ],
)
async def test_calendars_page_props(client, perms, flags):
    client.app.state.sm_events.settings.default_timezone = "bad/timezone"
    response = await client.get("/admin/events/calendars", headers=headers(*perms))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["component"] == "Events/Calendars"
    props = body["props"]
    assert (props["can_create"], props["can_manage"]) == flags
    assert (props["user_id"], props["default_timezone"], props["tenant"]) == (
        "owner",
        "UTC",
        "default",
    )


async def test_categories_page_needs_manage(client):
    assert (
        await client.get("/admin/events/categories", headers=headers("events.view"))
    ).status_code == 403
    client.app.state.sm_events.settings.content_locales = ("en", "de")
    response = await client.get(
        "/admin/events/categories", headers=headers("events.view", "events.manage")
    )
    assert response.status_code == 200, response.text
    assert response.json()["component"] == "Events/Categories"
    assert response.json()["props"]["content_locales"] == ["en", "de"]


async def test_categories_page_refuses_manager_without_api_view_permission(client):
    response = await client.get("/admin/events/categories", headers=headers("events.manage"))
    assert response.status_code == 403


def _inertia():
    return {"X-Inertia": "true", "X-Inertia-Version": "test"}


async def test_list_page_props(client):
    cals = await cast(client)
    client.app.state.sm_events.settings.content_locales = ("en", "de")
    response = await client.get("/admin/events/list", headers=STRANGER | _inertia())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["component"] == "Events/Events"
    props = body["props"]
    assert props["content_locales"] == ["en", "de"]
    assert props["categories"] == []
    by_id = {c["id"]: c for c in props["calendars"]}
    assert set(by_id) >= {cals["I"], cals["U"]}
    assert by_id[cals["I"]]["can_write_events"] is True
    assert {"id", "name", "color", "can_write_events", "default_timezone"} <= set(by_id[cals["I"]])
    assert props["can_create"] is True


async def test_list_page_cannot_create_for_a_viewer(client):
    await cast(client)
    response = await client.get("/admin/events/list", headers=VIEWER | _inertia())
    assert response.status_code == 200, response.text
    props = response.json()["props"]
    assert props["can_create"] is False
    assert all(c["can_write_events"] is False for c in props["calendars"])


async def test_editor_new_needs_write(client):
    cals = await cast(client)
    url = f"/admin/events/edit/new?calendar={cals['I']}"
    assert (await client.get(url, headers=VIEWER | _inertia())).status_code == 404
    response = await client.get(url, headers=STRANGER | _inertia())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["component"] == "Events/EventEditor"
    props = body["props"]
    assert props["event_id"] is None
    assert props["calendar"]["id"] == cals["I"]
    assert {"name", "default_timezone"} <= set(props["calendar"])
    assert props["default_timezone"] == props["calendar"]["default_timezone"]
    assert "content_locales" in props and "categories" in props


async def test_editor_new_without_calendar_is_404(client):
    await cast(client)
    response = await client.get("/admin/events/edit/new", headers=STRANGER | _inertia())
    assert response.status_code == 404


async def test_editor_existing_event(client):
    cals = await cast(client)
    event = await seed_event(client, cals["I"])
    response = await client.get(f"/admin/events/edit/{event['id']}", headers=STRANGER | _inertia())
    assert response.status_code == 200, response.text
    props = response.json()["props"]
    assert props["event_id"] == event["id"]
    assert props["calendar"]["id"] == cals["I"]


async def test_editor_invisible_event_404(client):
    cals = await cast(client)
    event = await seed_event(client, cals["I"])  # a draft
    response = await client.get(f"/admin/events/edit/{event['id']}", headers=VIEWER | _inertia())
    assert response.status_code == 404
    gone = await client.get(
        "/admin/events/edit/00000000-0000-0000-0000-000000000000",
        headers=STRANGER | _inertia(),
    )
    assert gone.status_code == 404
