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
from fastapi import APIRouter, FastAPI, Request
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from inertia import InertiaConfig, inertia_dependency_factory
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.models import Base, Record, RecordType
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware

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
            request.state.user = SimpleNamespace(
                id=f"test:{raw}", email="test@example.com", roles=roles_list
            )
        return await call_next(request)


async def build_app(tmp_path: Any, db_state: Any = None) -> tuple[FastAPI, Any]:
    """Every router mounted at its real prefix, exactly as
    ``wire_module_routes`` does in production.

    ``db_state`` overrides the throwaway ``:memory:`` database with one the
    caller already owns — the perf suite runs against a seeded file-backed
    SQLite database and needs the endpoints wired to *that* one, not to a
    fresh empty one. Its schema is assumed to exist; the default path still
    creates it.
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
        db_state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
        register_listeners(db_state)
        async with db_state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    registry = PermissionRegistry()
    module.register_permissions(registry)
    _register_roles(registry)
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)

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

    # Wired through the hook the host calls, not by hand: the deferred-job
    # drain is what makes the reindex run *after* the request's session has
    # been committed and closed, and a harness without it would prove the
    # endpoints work under an ordering production does not have.
    module.register_middleware(app)
    app.add_middleware(_HeaderAuthMiddleware)
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
