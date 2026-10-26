"""A host running news' public surface *and* pagebuilder's, for the site 404 (#248).

News renders a missing article as pagebuilder's ``PublicNotFound`` page inside
the site's frame, which only exists where pagebuilder is mounted. The ordinary
harness (``conftest._build_app``) mounts news alone; this adds pagebuilder the
way a host does — settings pre-seeded, ``on_startup`` run — before news'
``on_startup``, so both modules agree on the content languages. A plain module
(``tests`` is on ``pythonpath``), like ``tenant_app``.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from conftest import _build_app
from httpx import ASGITransport, AsyncClient
from news import locales as news_locales
from news.module import NewsModule
from pagebuilder.layout_service import LayoutService
from pagebuilder.module import PagebuilderModule
from pagebuilder.settings import PagebuilderSettings
from simple_module_db import tenant_context
from simple_module_hosting.middleware import TenantMiddleware
from tenant_app import HeaderTenant

HEADER = {"content": [{"type": "Heading", "props": {"id": "h", "text": "Site header"}}]}
FOOTER = {"content": [{"type": "Heading", "props": {"id": "f", "text": "Site footer"}}]}
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
COMPONENT = "PageBuilder/PublicNotFound"


async def site_client(
    *, locales: tuple[str, ...] = ("en",), multi: bool = False
) -> AsyncIterator[AsyncClient]:
    """An anonymous client on a host with both public surfaces.

    ``multi`` puts the framework's ``TenantMiddleware`` in the stack (so both
    modules detect MULTI) with an ``x-tenant`` header standing in for its
    resolver, on a strict database.
    """
    app, state = await _build_app(None)
    pagebuilder = PagebuilderModule()
    media = Path(tempfile.mkdtemp()) / "media"
    media.mkdir()
    pagebuilder.settings = PagebuilderSettings(
        media_root=media,
        content_locales=locales,
        default_content_locale=locales[0],
        site_name="Field Notes",
        scheduler_enabled=False,
    )
    pagebuilder.register_settings(app)
    if multi:
        app.add_middleware(HeaderTenant)
        app.add_middleware(TenantMiddleware)
        state.tenant_strict = True
    await pagebuilder.on_startup(app)
    await NewsModule().on_startup(app)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.app = app  # type: ignore[attr-defined]
            client.db_state = state  # type: ignore[attr-defined]
            yield client
    finally:
        await state.engine.dispose()
        # With pagebuilder mounted, news' startup publishes its content
        # locales process-wide; the next test must borrow afresh.
        news_locales.reset()


async def set_layout(client: AsyncClient, tenant: str = "default", **data: Any) -> None:
    """Give ``tenant`` a site header and footer."""
    with tenant_context(tenant):
        async with client.db_state.session_factory() as db:  # type: ignore[attr-defined]
            await LayoutService(db).update(
                header_data=data.get("header", HEADER), footer_data=data.get("footer", FOOTER)
            )
            await db.commit()
