"""Billing — plans, subscriptions and payment for tenants.

Plugs into the seams ``simple_module_tenants`` exposes and changes none of
them: it installs ``PlanEntitlements`` as ``app.state.tenants.entitlements``
(so the seat limit ``tenants`` already enforces comes from the tenant's plan),
reacts to membership events to keep per-seat quantities in step, and drives
``TenantService.set_status`` when a subscription stops being paid.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import weakref
from typing import TYPE_CHECKING

from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection

from sm_billing import constants as c

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI
    from simple_module_core.events import EventBus
    from simple_module_core.permissions import PermissionRegistry
    from simple_module_core.public_routes import PublicRouteRegistry

logger = logging.getLogger(__name__)

_VERSION = importlib.metadata.version("simple_module_billing")


class BillingModule(ModuleBase):
    meta = ModuleMeta(
        name=c.MODULE_NAME,
        route_prefix=c.ROUTE_PREFIX_API,
        view_prefix=c.VIEW_PREFIX,
        admin_view_prefix=c.ADMIN_VIEW_PREFIX,
        depends_on=[c._MODULE_TENANTS, c._MODULE_SETTINGS],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def register_settings(self, app: FastAPI) -> None:
        from sm_billing import crypto
        from sm_billing.services import BillingServices
        from sm_billing.settings import BillingSettings

        register_module_settings = importlib.import_module(
            "settings.registration"
        ).register_module_settings
        register_module_settings(
            app, c.PACKAGE, BillingSettings, lambda s: BillingServices(settings=s)
        )

        # Encrypt under the secret the running app holds (hosts may inject it
        # programmatically). Through a weakref: the provider is process-global
        # and a strong closure would keep discarded test apps alive.
        app_ref = weakref.ref(app)

        def _live_secret() -> str:
            live_app = app_ref()
            sm = getattr(getattr(live_app, "state", None), "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(_live_secret)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            c.MODULE_NAME,
            [c.PERM_VIEW, c.PERM_MANAGE, c.PERM_PLATFORM_VIEW, c.PERM_PLATFORM_MANAGE],
        )
        registry.map_role(c.ROLE_TENANT_OWNER, [c.PERM_VIEW, c.PERM_MANAGE])
        registry.map_role(c.ROLE_TENANT_ADMIN, [c.PERM_VIEW])

    def register_menu_items(self, registry: MenuRegistry) -> None:
        registry.add_many(
            [
                MenuItem(
                    label=c.MENU_LABEL,
                    url=c.MENU_URL,
                    icon=c.MENU_ICON,
                    order=c.MENU_ORDER,
                    section=MenuSection.SIDEBAR,
                    permissions=[c.PERM_VIEW],
                ),
                MenuItem(
                    label=c.ADMIN_MENU_LABEL,
                    url=c.ADMIN_MENU_URL,
                    icon=c.MENU_ICON,
                    order=c.MENU_ORDER,
                    section=MenuSection.ADMIN_SIDEBAR,
                    permissions=[c.PERM_PLATFORM_VIEW],
                    group=c.ADMIN_MENU_GROUP,
                    group_key=c.ADMIN_MENU_GROUP_KEY,
                ),
            ]
        )

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from sm_billing.endpoints import routers

        routers.include(api_router, view_router)

    def register_admin_routes(self, admin_router: APIRouter) -> None:
        from sm_billing.endpoints import routers

        routers.include_admin(admin_router)

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        # Stripe calls this unauthenticated; the signature is the auth.
        registry.add_exact(c.WEBHOOK_PATH, methods={"POST"})

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        if app is None:
            return
        from sm_billing import seats

        seats.subscribe(bus, app)

    async def on_startup(self, app: FastAPI) -> None:
        from sm_billing import startup

        await startup.run(app)
