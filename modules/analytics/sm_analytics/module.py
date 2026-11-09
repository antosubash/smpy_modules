"""Module discovery, settings, guards, permissions and lifecycle."""

import asyncio
from importlib import metadata, resources
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.body_limits import BodyLimitRegistry
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.module_settings import register_module_settings
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry, RateLimitRule
from simple_module_hosting.csrf import get_csrf_token
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission, resolved_permissions_for
from starlette.requests import Request

from sm_analytics.core import constants as c
from sm_analytics.core.runtime import Runtime
from sm_analytics.core.settings import AnalyticsSettings
from sm_analytics.core.tenancy import bind_admin


class AnalyticsModule(ModuleBase):
    meta = ModuleMeta(
        name=c.MODULE_NAME,
        route_prefix=c.API_PREFIX,
        view_prefix=c.VIEW_PREFIX,
        depends_on=[c._MODULE_SETTINGS],
        version=metadata.version("simple_module_analytics"),
        requires_framework=">=1.0,<2.0",
    )

    def register_settings(self, app: FastAPI) -> None:
        register_module_settings(app, c.PACKAGE, AnalyticsSettings, Runtime)

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from sm_analytics.web.endpoints.admin import router as admin
        from sm_analytics.web.endpoints.public import router as public

        api_router.include_router(admin)
        api_router.include_router(public)

        @view_router.get(
            "/",
            response_model=None,
            dependencies=[Depends(bind_admin), Depends(RequiresPermission(c.PERM_VIEW))],
        )
        async def dashboard(request: Request, inertia: InertiaDep):
            permissions = resolved_permissions_for(request)
            return await inertia.render(
                c._PAGE_DASHBOARD,
                {
                    "can_manage": "*" in permissions or c.PERM_MANAGE in permissions,
                    "csrf_token": get_csrf_token(request) or "",
                },
            )

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(c.MODULE_NAME, [c.PERM_VIEW, c.PERM_MANAGE])

    def register_menu_items(self, registry: MenuRegistry) -> None:
        registry.add(
            MenuItem(
                label="Analytics",
                label_key="analytics.menu.analytics",
                url=f"{c.VIEW_PREFIX}/",
                icon="bar-chart-3",
                order=117,
                permissions=[c.PERM_VIEW],
            )
        )

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        registry.add_exact(c.COLLECT_PATH, methods={"POST"})
        registry.add_exact(c.CONFIG_PATH, methods={"GET"})

    def register_body_limits(self, registry: BodyLimitRegistry) -> None:
        registry.add_exact(c.COLLECT_PATH, c.MAX_BODY_BYTES, methods={"POST"})

    def register_rate_limits(self, registry: RateLimitRegistry) -> None:
        registry.add_exact(
            c.COLLECT_PATH, RateLimitRule(c.COLLECT_RATE, key="ip", methods=frozenset({"POST"}))
        )
        registry.add_exact(
            c.CONFIG_PATH, RateLimitRule(c.CONFIG_RATE, key="ip", methods=frozenset({"GET"}))
        )

    def locale_dirs(self) -> dict[str, Path]:
        return {"analytics": Path(str(resources.files("sm_analytics") / "locales"))}

    async def on_startup(self, app: FastAPI) -> None:
        state = app.state.sm_analytics
        state.geo.path = state.settings.geo_database_path
        state.geo.enabled = state.settings.geo_enabled
        state.geo.status()
        if state.settings.scheduler_enabled:
            state.task = asyncio.create_task(state.run(app.state.sm.db.session_factory))

    async def on_shutdown(self, app: FastAPI) -> None:
        await app.state.sm_analytics.stop()
