"""The console's Reminders page: route, permissions and initial props (the screen is batch C)."""

from __future__ import annotations

import pytest
from fastapi.templating import Jinja2Templates
from simple_module_inertia import InertiaConfig, inertia_dependency_factory

from tests.support.app import as_user

V, M = "events.view", "events.manage"
URL = "/admin/events/reminders"


@pytest.fixture(autouse=True)
def inertia(events_app):
    app, _ = events_app
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(templates=Jinja2Templates(directory="."), version="test")
    )


def headers(*perms):
    return {**as_user("u", *perms), "X-Inertia": "true", "X-Inertia-Version": "test"}


async def test_reminders_page_props(client):
    got = await client.get(URL, headers=headers(V))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["component"] == "Events/Reminders"
    assert body["props"]["is_manager"] is False
    assert body["props"]["settings_url"] == "/admin/settings/"
    manager = (await client.get(URL, headers=headers(V, M))).json()
    assert manager["props"]["is_manager"] is True


async def test_reminders_page_needs_view(client):
    assert (await client.get(URL, headers=headers())).status_code == 403
    assert (await client.get(URL)).status_code == 401
