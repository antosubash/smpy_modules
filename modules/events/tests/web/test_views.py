"""Console routing, permissions and initial props against the real Inertia adapter."""

import pytest
from fastapi.templating import Jinja2Templates
from simple_module_inertia import InertiaConfig, inertia_dependency_factory

from tests.support.app import as_user


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
