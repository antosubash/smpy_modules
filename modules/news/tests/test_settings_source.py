"""News settings come from the database, like pagebuilder's.

``SM_NEWS_*`` and the root ``.env`` are no longer read. The invariants worth
pinning are the same two: env cannot reach the class, and the class is
registered where the host's hydrate step and the Settings screen look for it.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from news import constants
from news.module import NewsModule
from news.settings import NewsSettings
from settings.module_registry import ModuleSettingsRegistry


def test_the_env_var_is_ignored(monkeypatch):
    monkeypatch.setenv("SM_NEWS_PUBLIC_ROUTE_PREFIX", "/from-env")
    assert NewsSettings().public_route_prefix == "/news"


def test_a_dotenv_file_is_ignored(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("SM_NEWS_PUBLIC_ROUTE_PREFIX=/from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    assert NewsSettings().public_route_prefix == "/news"


def test_register_settings_publishes_the_class_for_hydration():
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    NewsModule().register_settings(app)

    registry = app.state.settings.module_registry
    assert registry.get(constants.PACKAGE) is NewsSettings
    assert isinstance(app.state.news.settings, NewsSettings)


def test_the_services_container_accepts_the_hydrated_instance():
    """The host's hydrate step assigns onto it; a frozen dataclass would raise."""
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    NewsModule().register_settings(app)

    app.state.news.settings = NewsSettings(public_route_prefix="/blog")
    assert app.state.news.settings.public_route_prefix == "/blog"


def test_the_public_prefix_announces_that_it_needs_a_restart():
    """It is read in ``on_startup`` to mount the viewer and exempt the path."""
    extra = NewsSettings.model_fields["public_route_prefix"].json_schema_extra
    assert extra and extra.get("requires_restart") is True
