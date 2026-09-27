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

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from inertia import InertiaConfig, inertia_dependency_factory
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting.middleware import (
    TENANT_HEADER,
    InertiaLayoutDataMiddleware,
    TenantMiddleware,
)
from sm_records.models import Record, RecordType
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from sm_records.tenancy import configure, install_guard

from tests.harness_auth import (  # noqa: F401 - re-exported: tests import them from here
    ADMIN,
    ROLE_EDITOR,
    ROLE_EDITOR_TWO,
    ROLE_MANAGER,
    ROLE_NONE,
    ROLE_VIEWER,
    TEST_TENANT_HEADER,
    _HeaderAuthMiddleware,
    _register_roles,
    roles,
)
from tests.pg_support import make_db_state


async def build_app(
    tmp_path: Any, db_state: Any = None, *, menus: bool = False, tenancy: str = "single"
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

    ``tenancy="multi"`` installs the framework's ``TenantMiddleware`` reading
    ``X-Tenant-ID``, where the host puts it — inside auth and inside the
    module's middleware — so the harness has the production stack shape
    (tenancy design §K). Either way the tenancy guard is on, as
    ``on_startup`` leaves it in a host.
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
    if tenancy == "multi":
        app.add_middleware(TenantMiddleware, header=TENANT_HEADER)
    module.register_middleware(app)
    app.add_middleware(_HeaderAuthMiddleware)
    configure(app)
    install_guard(db_state.sync_session_class)
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


def field(key: str, type_: str = "text", **options: Any) -> dict:
    """A full API field definition. ``required``/``unique``/``indexed`` are
    flags; every other keyword (``target_type``, ``on_delete``, ``choices``)
    lands in ``options``."""
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": options.pop("required", False),
        "unique": options.pop("unique", False),
        "indexed": options.pop("indexed", True),
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def api_type(
    client, key: str, fields: list[dict], *, actor: str = ADMIN, **cols: Any
) -> dict:
    """Create a type through ``POST /api/records/types`` and assert the 201."""
    resp = await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": fields, **cols},
        headers=roles(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def api_record(client, key: str, data: dict, *, actor: str = ADMIN, **cols: Any) -> dict:
    """Create a record through ``POST …/types/{key}/records`` and assert the 201."""
    resp = await client.post(
        f"/api/records/types/{key}/records", json={"data": data, **cols}, headers=roles(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()
