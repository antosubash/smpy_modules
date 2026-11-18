"""Console props that come from the plugin registry: enabled sources and event types."""

import pytest
from fastapi.templating import Jinja2Templates
from simple_module_inertia import InertiaConfig, inertia_dependency_factory

from tests.support.events_http import STRANGER, cast


@pytest.fixture(autouse=True)
def inertia(events_app):
    app, _ = events_app
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(templates=Jinja2Templates(directory="."), version="test")
    )


def _inertia():
    return {"X-Inertia": "true", "X-Inertia-Version": "test"}


async def test_calendar_page_lists_the_sources_enabled_on_shown_calendars(client, monkeypatch):
    from sm_events.calendar import registry

    from tests.support.sources import FakeSource, install

    install(monkeypatch, FakeSource("acme:fake"), FakeSource("acme:other"))
    try:
        cals = await cast(client)
        from sm_events.models import Calendar
        from sqlalchemy import select

        from tests.support.events_http import run

        async def enable(db):
            import uuid

            for key, ids in (("I", ["acme:fake", "gone:x"]), ("P", ["acme:other"])):
                cal = (
                    await db.execute(select(Calendar).where(Calendar.id == uuid.UUID(cals[key])))
                ).scalar_one()
                cal.sources = [{"id": i, "settings": {"secret": 1}} for i in ids]

        await run(client, enable)
        response = await client.get("/admin/events/", headers=STRANGER | _inertia())
        # The stranger sees I and U, not P: only the sources of shown calendars, and only
        # installed ones, with no settings.
        assert response.json()["props"]["sources"] == [
            {"id": "acme:fake", "label_key": "acme.fake", "color": None}
        ]
    finally:
        registry.reset_registry()


async def test_calendar_and_editor_props_list_types(client, monkeypatch):
    from tests.support.sources import install_talk

    install_talk(monkeypatch)
    cals = await cast(client)
    expected = [
        {"id": "event", "label_key": "events.types.event", "icon": None},
        {"id": "acme:talk", "label_key": "acme.types.talk", "icon": "mic"},
    ]
    page = await client.get("/admin/events/", headers=STRANGER | _inertia())
    assert page.json()["props"]["types"] == expected
    editor = await client.get(
        f"/admin/events/edit/new?calendar={cals['U']}", headers=STRANGER | _inertia()
    )
    assert editor.status_code == 200, editor.text
    assert editor.json()["props"]["types"] == expected
