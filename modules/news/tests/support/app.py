"""Shared test application and client harness."""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from news.core.constants import PERM_EDIT, PERM_PUBLISH, PERM_VIEW
from news.module import NewsModule

# ``pg_support`` owns the one decision both database fixtures make: in-memory
# SQLite, or the Postgres database ``SM_TEST_DATABASE_URL`` names. It is also
# where "news' tables, plus pagebuilder's where installed" is spelled out.
from pg_support import make_db_state
from simple_module_core.menu import MenuRegistry
from simple_module_core.module_settings import ModuleSettingsRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting.middleware import InertiaLayoutDataMiddleware
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from starlette.middleware.sessions import SessionMiddleware

from tests.support.csrf_support import add_token_route, arm_csrf
from tests.support.stub_auth import StubAuthMiddleware

_SHELL = (
    # Shaped like the host's page, not a bare `<html></html>`: a `<head>` with a
    # fixed app title and the `{% inertia_head %}` slot that stays empty without
    # SSR. `endpoints.public._head` writes an article's real metadata into that
    # head, and against a stub with nowhere to write it every test asserting on
    # server-rendered metadata would pass by asserting nothing.
    "<html lang=\"en\"><head><title>SimpleModule</title>{% inertia_head %}</head>"
    "<body>{% inertia_body %}</body></html>"
)


ROLE_EDITOR = "news-editor"
#: ``news.edit`` without ``news.publish`` — the case every workflow route that
#: puts something in front of readers has to refuse. This separation used to be
#: pagebuilder's, enforced by requiring its permissions on the routes that wrote
#: a page; owning the content means owning the separation.
ROLE_AUTHOR = "news-author"
ROLE_VIEWER = "news-viewer"


async def _build_app(
    user: Any, *, mount_public: bool = False, db_file: Path | None = None, layout: bool = False
) -> tuple[FastAPI, Any]:
    module = NewsModule()
    app = FastAPI()

    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    db_state = await make_db_state(file=db_file)  # a file: racing requests (#209)

    registry = PermissionRegistry()
    registry.add_group("News", [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_AUTHOR, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)
    # News' settings are DB-backed, so ``register_settings`` registers the class
    # against the settings module's registry rather than reading the
    # environment. Nothing hydrates it here: these tests want the declared
    # defaults, which is exactly what the container is built from.
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)

    # Minimal Inertia config — enough to render without the real host
    # templates. News serves its own public viewer, so the render happens here.
    # See ``_SHELL`` for why it is shaped like the host's page rather than a stub.
    templates_dir = Path(tempfile.mkdtemp()) / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "index.html").write_text(_SHELL)
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(
            environment="development",
            version="1.0",
            dev_url="http://localhost:5050",
            templates=Jinja2Templates(directory=str(templates_dir)),
            root_template_filename="index.html",
            entrypoint_filename="main.tsx",
            root_directory=".",
            use_flash_errors=True,
        )
    )

    if layout:
        # The framework's layout props, ``csrfToken`` among them (#342). Inside
        # the stub auth, as in the host, so it sees the signed-in user.
        app.add_middleware(
            InertiaLayoutDataMiddleware, menu_registry=MenuRegistry(), permission_registry=registry
        )
    app.add_middleware(StubAuthMiddleware, user=user)
    add_token_route(app)
    # Inertia reads flashed errors off the session on every render, so the
    # public viewer cannot answer at all without this. Added last so it ends up
    # outermost at runtime — Starlette runs the last-added middleware first on
    # the way in — which matches the host's own order.
    app.add_middleware(SessionMiddleware, secret_key="news-tests")

    if mount_public:
        # Most fixtures skip this: the admin API is what they exercise, and
        # ``on_startup`` mounts a router per content locale, which is
        # process-global. The public viewer only exists once it has run, so the
        # tests that are *about* the article's address ask for it.
        await module.on_startup(app)
    return app, db_state


async def _client(
    user: Any, *, mount_public: bool = False, db_file: Path | None = None
) -> AsyncIterator[AsyncClient]:
    app, state = await _build_app(user, mount_public=mount_public, db_file=db_file)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = state  # type: ignore[attr-defined]
        await arm_csrf(client)
        yield client
    await state.engine.dispose()
