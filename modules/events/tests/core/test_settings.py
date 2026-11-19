"""Settings: defaults, no environment source, restart marking, the services mount."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from simple_module_core.module_settings import ModuleSettingsRegistry
from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.module import EventsModule


def test_defaults():
    settings = EventsSettings()
    assert settings.default_timezone == "UTC"
    assert settings.content_locales == ("en",)


def test_public_fields():
    settings = EventsSettings()
    assert settings.public_prefix == "/events"
    assert settings.public_cache_seconds == 300
    assert settings.public_title == "Events"
    extra = EventsSettings.model_fields["public_prefix"].json_schema_extra or {}
    assert extra.get("requires_restart") is True
    cache_extra = EventsSettings.model_fields["public_cache_seconds"].json_schema_extra or {}
    assert "requires_restart" not in cache_extra


def test_settings_ignore_env(monkeypatch):
    monkeypatch.setenv("SM_EVENTS_DEFAULT_TIMEZONE", "Europe/Vienna")
    monkeypatch.setenv("DEFAULT_TIMEZONE", "Europe/Vienna")
    assert EventsSettings().default_timezone == "UTC"
    # Constructor kwargs are the one source: how the hydrator applies stored values.
    assert EventsSettings(default_timezone="Europe/Vienna").default_timezone == "Europe/Vienna"


def test_restart_fields():
    restart = {
        name
        for name, field in EventsSettings.model_fields.items()
        if (field.json_schema_extra or {}).get("requires_restart")
    }
    assert restart == {"content_locales", "public_prefix"}


def test_every_field_is_documented():
    for name, field in EventsSettings.model_fields.items():
        assert field.description, name


def test_register_settings_mounts_services():
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    EventsModule().register_settings(app)
    services = getattr(app.state, constants.PACKAGE)
    assert isinstance(services.settings, EventsSettings)


def test_pinned_settings_reach_the_container():
    module = EventsModule()
    module.settings = EventsSettings(default_timezone="Europe/Vienna")
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    assert app.state.sm_events.settings.default_timezone == "Europe/Vienna"


def test_import_max_bytes():
    settings = EventsSettings()
    assert settings.import_max_bytes == 5 * 1024 * 1024
    extra = EventsSettings.model_fields["import_max_bytes"].json_schema_extra or {}
    assert "requires_restart" not in extra


def test_subscription_defaults():
    settings = EventsSettings()
    assert settings.subscription_refresh_minutes == 60
    assert settings.allow_private_subscription_urls is False
    for name in ("subscription_refresh_minutes", "allow_private_subscription_urls"):
        extra = EventsSettings.model_fields[name].json_schema_extra or {}
        assert "requires_restart" not in extra  # read per fetch, applies at once
