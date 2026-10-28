"""HTTP test harness for the Images module: one app, header-driven users.

Wires the module through its own ``register_*`` hooks rather than
re-implementing them, so a test exercises the registrations production runs.
Role selection is per *request* (see :mod:`tests.stub_auth`): a test about
access needs the same collection seen by several callers in one test, and a
fresh app and client per caller would be clumsy for nothing.

Fixtures are imported by ``conftest`` so tests never need to know this module
exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from file_storage.backends.filesystem import FilesystemBackend
from httpx import ASGITransport, AsyncClient
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.events import EventBus
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting.middleware import TENANT_HEADER, TenantMiddleware
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from sm_images.module import ImagesModule
from sm_images.settings import ImagesSettings
from sm_images.tenancy import configure, install_guard

from tests.pg_support import make_db_state
from tests.stub_auth import (  # noqa: F401 - re-exported: tests import them from here
    ADMIN_PERMS,
    TEST_TENANT_HEADER,
    HeaderAuthMiddleware,
    as_user,
)


async def build_app(
    tmp_path: Any, db_state: Any = None, *, tenancy: str = "single"
) -> tuple[FastAPI, Any]:
    """Every router mounted at its real prefix, as ``wire_module_routes`` does.

    ``tenancy="multi"`` installs the framework's ``TenantMiddleware`` reading
    ``X-Tenant-ID``, where the host puts it - inside auth and inside the
    module's middleware - so the harness has the production stack shape. Either
    way the tenancy guard is on, as ``on_startup`` leaves it in a host.
    """
    module = ImagesModule()
    # Pre-seeded so ``register_settings`` hands the services container this
    # object instead of hydrating from a database the harness runs no lifespan
    # against.
    module.settings = ImagesSettings()

    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    module.register_exception_handlers(app)

    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    if db_state is None:
        # The suite's one place that decides which backend a test runs on, and
        # the one that creates the ``permissions`` table when it is installed.
        db_state = await make_db_state()

    # What ``app_builder`` does on a multi-tenant host: an unbound statement
    # over a tenant-owned table raises rather than reading every tenant.
    db_state.tenant_strict = tenancy == "multi"

    registry = PermissionRegistry()
    module.register_permissions(registry)
    # ``settings.secret_key``: what a host holds, and what direct-upload tokens are signed with.
    app.state.sm = SimpleNamespace(
        db=db_state,
        permissions=registry,
        event_bus=EventBus(),
        settings=SimpleNamespace(secret_key="images-test-secret"),
    )

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
    app.state.sm.inertia_config = inertia_config

    if tenancy == "multi":
        app.add_middleware(TenantMiddleware, header=TENANT_HEADER)
    app.add_middleware(HeaderAuthMiddleware)
    configure(app)
    install_guard(db_state.sync_session_class)
    app.state.images_module = module
    return app, db_state


@pytest_asyncio.fixture
async def images_app(tmp_path) -> AsyncIterator[tuple[FastAPI, Any]]:
    app, db_state = await build_app(tmp_path)
    yield app, db_state
    await db_state.engine.dispose()


@pytest_asyncio.fixture
async def client(images_app) -> AsyncIterator[AsyncClient]:
    """Anonymous by default. Pass ``headers=as_user(...)`` per request."""
    app, db_state = images_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        http_client.app = app  # type: ignore[attr-defined]
        http_client.db_state = db_state  # type: ignore[attr-defined]
        yield http_client


@pytest.fixture
def storage(images_app, tmp_path) -> FilesystemBackend:
    """A filesystem backend on ``tmp_path``, installed where the framework's
    ``file_storage`` module parks the live one (``app.state.file_storage.backend``)."""
    app, _ = images_app
    backend = FilesystemBackend(tmp_path / "storage")
    app.state.file_storage = SimpleNamespace(backend=backend)
    return backend
