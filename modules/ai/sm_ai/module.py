"""AI base module — connection configuration and the resolve service layer.

Provides no AI features of its own. Other modules depend on it for
``sm_ai.contracts`` (resolve_model / resolve_embedder) and its settings page;
consumers own agents, prompts and behaviour. There are no tables and no
migrations: configuration lives in the shared settings store.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import logging
import os
import weakref
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from sm_ai import constants

_VERSION = importlib.metadata.version("simple_module_ai")
logger = logging.getLogger(__name__)


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
        from simple_module_core.module_settings import register_module_settings

        from sm_ai import crypto, services
        from sm_ai.settings import AiSettings

        # Before #124 these seeded unset fields; now they are dead, and a
        # deployment that relied on them silently runs on the defaults.
        dead = sorted(k for k in os.environ if k.startswith("SM_AI_"))
        if dead:
            logger.warning(
                "Ignoring %s: the AI module reads no environment variables. "
                "Set them on /ai/ or with scripts/set_setting.py (see the ai operations docs).",
                ", ".join(dead),
            )

        # The factory installs the instance in the module-global holder AND
        # returns it for app.state.sm_ai — one shared object, so hydration and
        # hot reload (which assign .settings on it) are visible to contracts.
        register_module_settings(
            app,
            constants.PACKAGE,
            AiSettings,
            lambda s: services.install(services.AiServices(settings=s)),
            # The generic Settings screen links to /ai/ and refuses writes
            # (#164): a second editor would skip the provider and base-URL
            # checks, the embedding_dim bound and key encryption.
            manage_url=constants.MENU_URL,
        )

        # Hosts may inject ``secret_key`` programmatically
        # (``create_app(settings=...)``) rather than via env/.env; crypto must
        # encrypt under the secret the running app actually holds or stored
        # keys become unreadable. app.state.sm is assigned after this phase,
        # so resolve lazily — through a weakref, because the provider is a
        # process-global and a strong closure would keep a discarded app's
        # whole object graph alive (app-factory test suites build many).
        app_ref = weakref.ref(app)

        def _live_secret() -> str:
            live_app = app_ref()
            if live_app is None:
                return ""
            sm = getattr(live_app.state, "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(_live_secret)

    async def on_startup(self, app: FastAPI) -> None:
        """Register ``ai.requests`` with billing's meter registry, if billing runs.

        Billing is optional: without it nothing is metered (see ``metering``).
        """
        from sm_ai import metering

        metering.register_meter(app)

    def locale_dirs(self) -> dict[str, Path]:
        """Console strings, resolved through the package so a wheel install works."""
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(constants.MODULE_NAME, [constants.PERM_MANAGE])

    def register_menu_items(self, registry: MenuRegistry) -> None:
        registry.add(
            MenuItem(
                label=constants.MENU_LABEL,
                label_key=constants.MENU_LABEL_KEY,
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.SIDEBAR,
                group=constants.MENU_GROUP,
                group_key=constants.MENU_GROUP_KEY,
                roles=["admin"],
            )
        )

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from simple_module_hosting.csrf import RequiresCsrf

        from sm_ai.csrf import share_csrf_token
        from sm_ai.endpoints.api import router as api
        from sm_ai.endpoints.views import router as views

        # The write surface can redirect chat_base_url and thereby point the
        # stored provider key at an attacker's server. So the framework's CSRF
        # check runs on every write, and the view shares the token it wants.
        api_router.include_router(api, dependencies=[Depends(RequiresCsrf())])
        view_router.include_router(views, dependencies=[Depends(share_csrf_token)])
