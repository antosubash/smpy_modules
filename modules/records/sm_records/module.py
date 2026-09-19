"""Records module — admin-defined content types stored as JSON documents.

A YesSql-style document/index split: one document table holds every record's
payload, and typed index tables make declared fields queryable. No table is
ever created at runtime. Design: ``docs/plans/2026-09-19-records-module-design.md``.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from sm_records import constants

if TYPE_CHECKING:
    from fastapi import FastAPI

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only; a hardcoded string
# here would silently fall behind it.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class RecordsModule(ModuleBase):
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

    def __init__(self) -> None:
        super().__init__()
        # Pre-seeding this is how a test pins settings without a database:
        # ``register_settings`` hands it to the services container instead of
        # the pydantic defaults, and with no hydration step to overwrite it,
        # it is what every hook then reads.
        self.settings = None

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class and mount the services container.

        ``register_module_settings`` records the class so the host can hydrate
        it from the DB at lifespan start — it assigns the result onto the
        container this creates, which is why every later read goes through
        ``app.state.sm_records`` rather than a captured local.
        """
        from settings.registration import register_module_settings

        from sm_records.services import RecordsServices
        from sm_records.settings import RecordsSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            RecordsSettings,
            lambda defaults: RecordsServices(settings=self.settings or defaults),
        )

    def register_permissions(self, registry: PermissionRegistry) -> None:
        """Three static permissions — the only ones the role editor can show.

        Per-type access (``RecordType.allowed_roles``) narrows these at request
        time and is invisible here: ``register_permissions`` runs before the
        database is open, and types are created at runtime. Design doc §10.
        """
        registry.add_group(
            constants.PERM_GROUP,
            [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_MANAGE_TYPES],
        )

    def register_menu_items(self, registry: MenuRegistry) -> None:
        """Deliberately not role-gated: menu role filtering is a plain
        intersection with no admin bypass, so listing roles here would hide
        the entry from an ``admin`` user. The views carry their own
        permission dependencies."""
        # ``label_key`` is not on the released framework's ``MenuItem`` yet
        # (0.0.26); the literal label stands until it is, as in every sibling.
        registry.add(
            MenuItem(
                label="Records",
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.ADMIN_SIDEBAR,
                group=constants.MENU_GROUP,
            )
        )

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.PERM_GROUP: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet, and a top-level import would make one missing dependency
        # take the whole module — and its tables — out of discovery.
        from sm_records.endpoints.api import router as api
        from sm_records.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)
