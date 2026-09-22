"""HTTP test harness for the Records module: one app, header-driven roles.

Mirrors ``pagebuilder``'s ``_build_app``/``_client_for`` shape (wire the
module through its own ``register_*`` hooks rather than re-implementing
them) and ``news``'s stub-auth pattern. The one real difference: role
selection happens per *request* here, via an ``X-Test-Roles`` header, rather
than per client. An ``allowed_roles`` test needs the same type seen by two
different callers in the course of one test, and a fresh app+client per role
would make that clumsy for no benefit — nothing about permission resolution
here depends on which client object asked.

Split out of ``conftest.py`` for the 300-line cap; its fixtures are imported
there so tests never need to know this module exists.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from inertia import InertiaConfig, inertia_dependency_factory
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting.middleware import InertiaLayoutDataMiddleware
from simple_module_hosting.permissions import resolve_permissions
from sm_records.models import Record, RecordType
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from starlette.middleware.base import BaseHTTPMiddleware

from tests.pg_support import make_db_state

try:
    # Only present when the host also installs ``permissions`` — see
    # ``sm_records.deps``'s fallback import for why ``records`` cannot
    # require it. When it *is* installed (as in this repo's dev venv),
    # ``deps.RequiresPermission`` resolves to ``permissions.deps``'s version,
    # which (a) needs a real UUID for ``request.state.user.id`` rather than
    # this harness's plain ``"test:<roles>"`` string, and (b) queries
    # ``permissions_user_permission`` directly rather than falling back to
    # the role map when ``request.state.resolved_permissions`` is unset — so
    # both have to be provided here for the harness to behave like the real
    # request pipeline (``AuthMiddleware`` sets ``resolved_permissions``;
    # real user ids are UUIDs). Its table is created by
    # ``tests.pg_support.make_db_state``.
    import permissions.models  # noqa: F401

    _PERMISSIONS_INSTALLED = True
except ImportError:  # pragma: no cover - exercised only without `permissions`
    _PERMISSIONS_INSTALLED = False

#: Holds ``records.view`` + ``records.edit`` — the caller a ``allowed_roles``
#: test uses as the one who *should* pass.
ROLE_VIEWER = "records-viewer"
ROLE_EDITOR = "records-editor"
#: A second, distinct edit-capable role: holds the same static permission as
#: ``ROLE_EDITOR`` but is never on a type's ``allowed_roles`` list unless a
#: test puts it there — the caller who should be refused.
ROLE_EDITOR_TWO = "records-editor-two"
ROLE_MANAGER = "records-manager"
#: Registered nowhere: resolves to an empty permission set, same as any
#: role nobody mapped. Named for readability at call sites.
ROLE_NONE = "records-nobody"

ADMIN = "admin"
"""Resolves to the wildcard via ``DEFAULT_ROLE_PERMISSIONS`` with no mapping
of our own needed — the case a naive membership check over a literal
permission list would miss."""


def _register_roles(registry: PermissionRegistry) -> None:
    from sm_records.constants import PERM_EDIT, PERM_MANAGE_TYPES, PERM_VIEW

    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_EDITOR_TWO, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_MANAGER, [PERM_VIEW, PERM_EDIT, PERM_MANAGE_TYPES])


class _HeaderAuthMiddleware(BaseHTTPMiddleware):
    """``X-Test-Roles: role-a,role-b`` becomes ``request.state.user.roles``.

    No header at all leaves the request anonymous — the harness's stand-in
    for an unauthenticated caller, which ``RequiresPermission`` turns into a
    401 exactly as the framework's real auth middleware would.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        raw = request.headers.get("X-Test-Roles")
        if raw is not None:
            roles_list = [role.strip() for role in raw.split(",") if role.strip()]
            # A real UUID when ``permissions`` is installed — its checker
            # casts ``user.id`` with ``uuid.UUID(str(...))`` before it ever
            # gets to a role check that would otherwise short-circuit that;
            # deterministic (not random) so the same header always maps to
            # the same id within a test.
            user_id = (
                str(uuid.uuid5(uuid.NAMESPACE_DNS, raw))
                if _PERMISSIONS_INSTALLED
                else f"test:{raw}"
            )
            request.state.user = SimpleNamespace(
                id=user_id, email="test@example.com", roles=roles_list
            )
            # Mirrors ``AuthMiddleware`` (``simple_module_hosting/middleware.py``),
            # which runs ahead of every dependency in production. Without it,
            # ``permissions.deps.RequiresPermission`` (unlike the framework's
            # own, roles-only checker) has no role-map fallback of its own and
            # treats every caller as holding nothing but direct grants.
            registry = request.app.state.sm.permissions
            request.state.resolved_permissions = resolve_permissions(
                roles_list, role_map=registry.role_map
            )
        return await call_next(request)


async def build_app(
    tmp_path: Any, db_state: Any = None, *, menus: bool = False
) -> tuple[FastAPI, Any]:
    """Every router mounted at its real prefix, exactly as
    ``wire_module_routes`` does in production.

    ``db_state`` overrides the throwaway ``:memory:`` database with one the
    caller already owns — the perf suite runs against a seeded file-backed
    SQLite database and needs the endpoints wired to *that* one, not to a
    fresh empty one. Its schema is assumed to exist; the default path still
    creates it.

    ``menus`` adds the two pieces of the host that the sidebar needs: a
    ``MenuRegistry`` filled through ``register_menu_items``, and
    ``InertiaLayoutDataMiddleware``, which is what turns it into the ``menus``
    shared prop of a view response. Off by default because that middleware
    adds ``auth``/``menus``/``i18n`` to *every* Inertia payload, and the view
    tests assert the exact set of props their pages produce.
    """
    module = RecordsModule()
    # Pre-seeded so ``register_settings`` hands the services container this
    # object instead of hydrating from a database the harness doesn't run a
    # lifespan against — the same seam ``pagebuilder``'s harness uses.
    module.settings = RecordsSettings()

    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)

    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    if db_state is None:
        # ``make_db_state`` is the suite's one place that decides which backend
        # a test runs on — in-memory SQLite by default, Postgres when
        # ``RECORDS_TEST_URL`` is set — and the one place that creates the
        # ``permissions`` table the middleware above needs.
        db_state = await make_db_state()

    registry = PermissionRegistry()
    module.register_permissions(registry)
    _register_roles(registry)
    # A real bus, so every test in the suite runs the publish path this module
    # attaches to its writes (:mod:`sm_records.events`) rather than its
    # "no bus, do nothing" branch. With nobody subscribed it costs one
    # ``EventBus.publish`` that returns before gathering anything.
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry, event_bus=EventBus())

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "index.html").write_text("<html></html>")
    inertia_config = InertiaConfig(
        environment="development",
        version="1.0",
        dev_url="http://localhost:5050",
        templates=Jinja2Templates(directory=str(templates_dir)),
        root_template_filename="index.html",
        entrypoint_filename="main.tsx",
        root_directory=".",
    )
    app.state.inertia_dependency = inertia_dependency_factory(inertia_config)
    # Parked where the framework parks it, because the view router's error
    # class renders the host's Inertia error page from exactly this attribute
    # (``endpoints/api/_errors.RecordsViewErrorRoute``). Without it those
    # routes fall back to JSON and the test that a browser gets HTML would
    # pass against the behaviour it exists to refuse.
    app.state.sm.inertia_config = inertia_config

    if menus:
        # Added before the module's own middleware so it ends up *outside* it:
        # ``add_middleware`` is LIFO, which is exactly the order
        # ``_phase_helpers.install_middleware`` produces in the real host, and
        # it is what lets a sync done by ``MenuSyncMiddleware`` be visible to
        # the shared props of the same request.
        menu_registry = MenuRegistry()
        module.register_menu_items(menu_registry)
        app.add_middleware(
            InertiaLayoutDataMiddleware,
            menu_registry=menu_registry,
            permission_registry=registry,
        )
        app.state.menu_registry = menu_registry

    # Wired through the hook the host calls, not by hand: the deferred-job
    # drain is what makes the reindex run *after* the request's session has
    # been committed and closed, and a harness without it would prove the
    # endpoints work under an ordering production does not have.
    module.register_middleware(app)
    app.add_middleware(_HeaderAuthMiddleware)
    # Parked so a test can run the lifespan hook the host would run — the
    # anonymous read API is mounted from ``on_startup`` (its prefix is a
    # settings value), so a test of it has to reach the module instance.
    app.state.records_module = module
    return app, db_state


@pytest_asyncio.fixture
async def records_app(tmp_path) -> AsyncIterator[tuple[FastAPI, Any]]:
    app, db_state = await build_app(tmp_path)
    yield app, db_state
    await db_state.engine.dispose()


@pytest_asyncio.fixture
async def client(records_app) -> AsyncIterator[AsyncClient]:
    """Anonymous by default. Pass ``headers=roles(...)`` per request to act
    as one or more roles — see :func:`roles`."""
    app, db_state = records_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        http_client.app = app  # type: ignore[attr-defined]
        http_client.db_state = db_state  # type: ignore[attr-defined]
        yield http_client


def roles(*names: str) -> dict[str, str]:
    """``client.get(url, headers=roles(ADMIN))`` — the one header the stub
    auth middleware reads."""
    return {"X-Test-Roles": ",".join(names)}


async def seed_type(db_state: Any, key: str, fields: list[dict], **cols: Any) -> RecordType:
    """Insert a record type directly, committed on its own session so an API
    request through the client's session sees it. Mirrors
    ``news.conftest.make_page``."""
    async with db_state.session_factory() as session:
        rtype = RecordType(
            key=key,
            label=cols.pop("label", key.title()),
            label_plural=cols.pop("label_plural", f"{key.title()}s"),
            fields=fields,
            **cols,
        )
        session.add(rtype)
        await session.commit()
        await session.refresh(rtype)
        return rtype


async def seed_record(db_state: Any, rtype: RecordType, data: dict, **cols: Any) -> Record:
    async with db_state.session_factory() as session:
        record = Record(
            type_id=rtype.id,
            data=data,
            schema_version=cols.pop("schema_version", rtype.schema_version),
            **cols,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record
