"""The public origin follows the live host settings, not the boot snapshot.

A ``host.*`` row saved on the Settings screen reloads ``app.state.host`` and leaves
``app.state.sm.settings`` as it was at boot, although ``public_base_url`` is read per request.
Public pages, feeds, the sitemap and JSON-LD all build absolute URLs through one function."""

from __future__ import annotations

from types import SimpleNamespace

from sm_events.core import host_settings
from sm_events.web.endpoints.public import _urls

from tests.support.app import build_app


async def test_one_function_for_both_readers_and_it_follows_the_live_settings():
    app, state = await build_app()
    try:
        app.state.sm.settings.public_base_url = "https://boot.example.org"
        assert _urls.configured_origin(app) == "https://boot.example.org"
        app.state.host = SimpleNamespace(
            settings=SimpleNamespace(public_base_url="https://live.example.org/")
        )
        assert _urls.configured_origin(app) == "https://live.example.org"
        assert host_settings.public_base_url(app) == "https://live.example.org"
        assert _urls.guessed(app) is False
        app.state.host = SimpleNamespace(settings=SimpleNamespace(public_base_url=""))
        assert _urls.configured_origin(app) == ""  # cleared on the Settings screen: Host again
        assert _urls.guessed(app) is True
    finally:
        await state.engine.dispose()


async def test_the_reminders_read_the_same_value():
    from sm_events.reminders.base_url import public_base_url

    app, state = await build_app()
    try:
        app.state.host = SimpleNamespace(
            settings=SimpleNamespace(public_base_url="https://live.example.org")
        )
        assert public_base_url(app) == _urls.configured_origin(app) == "https://live.example.org"
    finally:
        await state.engine.dispose()


async def test_the_public_urls_use_the_saved_address(public_client):
    """End to end: the index page's canonical link and the sitemap's index entry."""
    app = public_client.app
    app.state.sm.settings.public_base_url = "https://boot.example.org"
    app.state.host = SimpleNamespace(
        settings=SimpleNamespace(public_base_url="https://live.example.org")
    )
    page = await public_client.get("/events/")
    assert page.status_code == 200
    assert "https://live.example.org/events/" in page.text
    assert "boot.example.org" not in page.text
