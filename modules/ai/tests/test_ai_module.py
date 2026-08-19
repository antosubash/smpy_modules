"""Module registration: meta, settings holder wiring, permissions, menu."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from sm_ai import constants, services
from sm_ai.module import AiModule


class TestMeta:
    def test_meta(self):
        assert AiModule.meta.name == constants.MODULE_NAME
        assert AiModule.meta.route_prefix == constants.ROUTE_PREFIX_API
        assert AiModule.meta.view_prefix == constants.VIEW_PREFIX
        assert constants._MODULE_SETTINGS in AiModule.meta.depends_on

    def test_requires_framework(self):
        assert AiModule.meta.requires_framework is not None


class TestRegisterSettings:
    def test_installs_holder_and_registers_class(self):
        # A minimal stand-in for the settings module's app.state contribution.
        app = FastAPI()
        app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
        try:
            AiModule().register_settings(app)
            assert app.state.settings.module_registry.get(constants.PACKAGE) is not None
            state_services = getattr(app.state, constants.PACKAGE)
            # The module-global holder and app.state hold the SAME instance —
            # that identity is what makes hot reload visible to contracts.
            assert services.current_settings() is state_services.settings
        finally:
            services.reset()


class TestPermissions:
    def test_manage_permission_registered(self):
        registry = PermissionRegistry()
        AiModule().register_permissions(registry)
        assert constants.PERM_MANAGE in registry.all_permissions


class TestMenu:
    def test_menu_entry(self):
        registry = MenuRegistry()
        AiModule().register_menu_items(registry)
        items = [i for i in registry.all_items if i.url == constants.MENU_URL]
        assert len(items) == 1
        assert items[0].group == constants.MENU_GROUP
