"""Settings defaults, env independence and the module's registration."""

from __future__ import annotations

import gc
from types import SimpleNamespace

from fastapi import FastAPI
from simple_module_core.module_settings import ModuleSettingsRegistry, module_settings_registry
from sm_newsletter.core import constants, crypto
from sm_newsletter.core.services import NewsletterServices
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.module import NewsletterModule


def test_defaults_match_the_spec():
    s = NewsletterSettings()
    assert (s.transport, s.smtp_host, s.smtp_port, s.smtp_security) == (
        "smtp",
        "smtp-relay.gmail.com",
        587,
        "starttls",
    )
    assert (s.smtp_username, s.smtp_password) == ("", "")
    assert (s.from_address, s.from_name, s.reply_to) == ("", "", "")
    assert (s.daily_limit, s.per_minute_limit) == (9500, 30)
    assert (s.tracking_opens, s.tracking_clicks) == (True, True)
    assert s.physical_address == ""


def test_every_field_is_documented():
    for name, field in NewsletterSettings.model_fields.items():
        assert field.description, name


def test_settings_ignore_env(monkeypatch):
    monkeypatch.setenv("SM_NEWSLETTER_DAILY_LIMIT", "1")
    monkeypatch.setenv("DAILY_LIMIT", "1")
    assert NewsletterSettings().daily_limit == 9500
    assert NewsletterSettings(daily_limit=7).daily_limit == 7


def test_no_field_needs_a_restart():
    for name, field in NewsletterSettings.model_fields.items():
        assert not (field.json_schema_extra or {}).get("requires_restart"), name


def test_password_never_in_repr():
    assert "secret" not in repr(NewsletterSettings(smtp_password="secret"))


def _app() -> FastAPI:
    app = FastAPI()
    app.state.module_settings_registry = ModuleSettingsRegistry()
    return app


def test_register_settings_mounts_services():
    app = _app()
    NewsletterModule().register_settings(app)
    services = app.state.sm_newsletter
    assert isinstance(services, NewsletterServices)
    assert isinstance(services.settings, NewsletterSettings)


def test_pinned_settings_win():
    app = _app()
    module = NewsletterModule()
    module.settings = NewsletterSettings(daily_limit=3)
    module.register_settings(app)
    assert app.state.sm_newsletter.settings.daily_limit == 3


def test_registry_reports_the_settings_url():
    app = _app()
    NewsletterModule().register_settings(app)
    registry = module_settings_registry(app)
    assert (
        registry.manage_url(constants.PACKAGE)
        == constants.SETTINGS_URL
        == "/admin/newsletter/settings"
    )


def test_secret_provider_reads_the_live_apps_secret_then_yields_nothing():
    app = _app()
    app.state.sm = SimpleNamespace(settings=SimpleNamespace(secret_key="live-secret"))
    NewsletterModule().register_settings(app)
    provider = crypto._secret_provider
    assert provider is not None
    assert provider() == "live-secret"
    del app
    gc.collect()
    assert provider() == ""
