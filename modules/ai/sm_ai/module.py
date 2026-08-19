"""AI base module — connection configuration and the resolve service layer.

Provides no AI features of its own. Other modules depend on it for
``sm_ai.contracts`` (resolve_model / resolve_embedder) and its settings page;
consumers own agents, prompts and behaviour. There are no tables and no
migrations: configuration lives in the shared settings store.
"""

from __future__ import annotations

import importlib.metadata

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from sm_ai import constants

_VERSION = importlib.metadata.version("simple_module_ai")


class AiModule(ModuleBase):
    meta = ModuleMeta(
        name=constants.MODULE_NAME,
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=[constants._MODULE_SETTINGS],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def register_settings(self, app: FastAPI) -> None:
        from settings.registration import register_module_settings

        from sm_ai import crypto, services
        from sm_ai.settings import AiSettings

        # The factory installs the instance in the module-global holder AND
        # returns it for app.state.sm_ai — one shared object, so hydration and
        # hot reload (which assign .settings on it) are visible to contracts.
        register_module_settings(
            app,
            constants.PACKAGE,
            AiSettings,
            lambda s: services.install(services.AiServices(settings=s)),
        )

        # Hosts may inject ``secret_key`` programmatically
        # (``create_app(settings=...)``) rather than via env/.env; crypto must
        # encrypt under the secret the running app actually holds or stored
        # keys become unreadable. app.state.sm is assigned after this phase,
        # so resolve lazily.
        def _live_secret() -> str:
            sm = getattr(app.state, "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(_live_secret)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(constants.MODULE_NAME, [constants.PERM_MANAGE])

    def register_menu_items(self, registry: MenuRegistry) -> None:
        registry.add(
            MenuItem(
                label="AI",
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.SIDEBAR,
                group=constants.MENU_GROUP,
                roles=["admin"],
            )
        )

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from sm_ai.endpoints.api import router as api
        from sm_ai.endpoints.views import router as views
        from sm_ai.security import mint_csrf_token, verify_csrf

        # The write surface can redirect chat_base_url and thereby point the
        # stored provider key at an attacker's server — CSRF is enforced on
        # the API (unsafe methods) and the token minted on the admin view.
        api_router.include_router(api, dependencies=[Depends(verify_csrf)])
        view_router.include_router(views, dependencies=[Depends(mint_csrf_token)])

    def register_middleware(self, app: FastAPI) -> None:
        from sm_ai.security import CsrfCookieMiddleware

        app.add_middleware(CsrfCookieMiddleware)
