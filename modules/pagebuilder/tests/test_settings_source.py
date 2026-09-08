"""Settings come from the database, and from nowhere else.

The module used to read ``SM_PAGEBUILDER_*`` and the repo's root ``.env``.
Both are gone: the class is registered with the framework's settings module
and hydrated from the store at lifespan start. These tests pin the parts of
that which are easy to undo by accident — a stray ``env_prefix``, a field that
silently stops telling the Settings screen it needs a restart, or an auth flag
baked into the router at build time where no stored value can reach it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from pagebuilder.module import PagebuilderModule
from pagebuilder.settings import PagebuilderSettings
from settings.hydrate import hydrate_settings, value_type_for_field
from settings.module_registry import ModuleSettingsRegistry

PACKAGE = "pagebuilder"


@pytest.mark.parametrize(
    ("env_var", "field", "default"),
    [
        ("SM_PAGEBUILDER_CONTENT_LOCALES", "content_locales", ("en",)),
        ("SM_PAGEBUILDER_PUBLIC_ROUTE_PREFIX", "public_route_prefix", "/p"),
        ("SM_PAGEBUILDER_REQUIRES_AUTH", "requires_auth", True),
    ],
)
def test_environment_variables_are_ignored(monkeypatch, env_var, field, default):
    """A leftover variable must not outrank what an operator can see and edit."""
    monkeypatch.setenv(env_var, '["en","de"]' if field == "content_locales" else "false")
    assert getattr(PagebuilderSettings(), field) == default


def test_a_dotenv_file_is_ignored(monkeypatch, tmp_path):
    """Including the repo root's, which pydantic-settings would read itself."""
    (tmp_path / ".env").write_text('SM_PAGEBUILDER_PUBLIC_ROUTE_PREFIX=/from-dotenv\n')
    monkeypatch.chdir(tmp_path)
    assert PagebuilderSettings().public_route_prefix == "/p"


def test_keyword_arguments_still_win():
    """The one remaining source: what the hydrator passes in."""
    settings = PagebuilderSettings(content_locales=("en", "de"))
    assert settings.content_locales == ("en", "de")


def test_register_settings_publishes_the_class_for_hydration():
    """Without this the Settings screen has no fields and hydration no class."""
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    PagebuilderModule().register_settings(app)

    assert app.state.settings.module_registry.get(PACKAGE) is PagebuilderSettings
    assert isinstance(app.state.pagebuilder.settings, PagebuilderSettings)


async def test_stored_values_reach_the_module():
    """End to end through the framework's hydrator, with a stubbed store."""

    class _Store:
        async def get_overrides(self, package):
            assert package == PACKAGE
            return {
                "content_locales": ('["en","de"]', "json"),
                "public_route_prefix": ("/site", "string"),
            }

    hydrated = await hydrate_settings(PagebuilderSettings, _Store(), PACKAGE)
    assert hydrated.content_locales == ("en", "de")
    assert hydrated.public_route_prefix == "/site"


@pytest.mark.parametrize(
    "field",
    [
        "public_route_prefix",
        "content_locales",
        "default_content_locale",
        "media_root",
        "media_url_prefix",
        "sitemap_enabled",
        "robots_enabled",
        "scheduler_enabled",
    ],
)
def test_boot_read_fields_announce_that_they_need_a_restart(field):
    """These decide route topology, which is settled once, in ``on_startup``.

    A field read there but not marked would be a control the Settings screen
    presents as live and the running app ignores until someone restarts it.
    """
    extra = PagebuilderSettings.model_fields[field].json_schema_extra
    assert extra and extra.get("requires_restart") is True, field


def test_the_locale_list_stores_as_json():
    """A tuple has to survive the round trip through a text column."""
    assert value_type_for_field(PagebuilderSettings, "content_locales") == "json"


async def test_requires_auth_is_decided_per_request(tmp_path):
    """The routers are built before the store is read, so the flag can't be
    baked into the dependency list — a stored ``false`` would never apply.

    Flipping it on a running app is the sharpest way to show the difference:
    the same client, the same route, two answers.
    """
    from conftest import _build_app, _client_for

    app, cleanup = await _build_app(
        tmp_path, requires_auth=False, csrf_protect=False, inject_user=False
    )
    try:
        async with _client_for(app) as client:
            assert (await client.get("/api/pagebuilder/pages")).status_code == 200
            app.state.pagebuilder.settings = app.state.pagebuilder.settings.model_copy(
                update={"requires_auth": True}
            )
            assert (await client.get("/api/pagebuilder/pages")).status_code == 401
    finally:
        await cleanup()
