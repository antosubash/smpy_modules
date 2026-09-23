"""Two tenants over HTTP, for the isolation matrix — tenancy design K1, K2, K3.

``acme`` and ``globex`` each hold a public, translatable type keyed ``post``.
Each has a record with **the same uuid** (:data:`SAME`), the same slug
(``hello``) and therefore the same translation group, all written by the real
import endpoint. ``acme`` also holds what ``globex`` must never reach: a
second record (:data:`ACME_ONLY`, which references ``SAME``), a trashed one
(:data:`ACME_TRASHED`), a German sibling of ``SAME``, and a whole type
(:data:`SECRET`) that ``globex`` has no type of that key for.

Every probe asks as ``globex`` for one of ``acme``'s things, and asks again
for a thing that exists nowhere; the two answers must be equal once each
probe string is replaced by its name (:func:`same_as_unknown`). That is what
"no oracle" means here: the body names what the caller sent, and nothing
else.

:func:`covers` records which route a test is the isolation case for, and
:func:`route_table` lists the routes the module really mounts, so
``test_every_route_has_an_isolation_case`` fails for a route nobody wrote a
case for.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient, Response
from settings.module_registry import ModuleSettingsRegistry
from sm_records import boot, constants
from sm_records.models import RecordType, table_sets
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from sqlalchemy import select

from tests.app_harness import ADMIN, TEST_TENANT_HEADER, build_app, roles

ACME, GLOBEX = "acme", "globex"
POST, SECRET, NO_KEY = "post", "secret", "nosuch"
SAME = "5" * 32
ACME_ONLY, ACME_TRASHED, ACME_SECRET = "a" * 32, "b" * 32, "c" * 32
GLOBEX_REF = "9" * 32
NO_UUID = "f" * 32
NO_REVISION = 987654321
API = "/api/records/types"
PUBLIC = "/api/records/public"
VIEW = "/admin/records"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}

FIELDS = [
    {"key": "title", "type": "text", "label": "Title", "indexed": True},
    {"key": "score", "type": "number", "label": "Score", "indexed": True},
    {
        "key": "link",
        "type": "relation",
        "label": "Link",
        "indexed": True,
        "options": {"target_type": POST},
    },
]


def as_(tenant: str | None, *role_names: str) -> dict[str, str]:
    """A signed-in caller whose account is in ``tenant``."""
    headers = roles(*(role_names or (ADMIN,)))
    if tenant is not None:
        headers[TEST_TENANT_HEADER] = tenant
    return headers


def reader(tenant: str) -> dict[str, str]:
    """An anonymous caller naming ``tenant`` in the framework's header."""
    return {"X-Tenant-ID": tenant}


def row(uuid: str, title: str, score: int, **extra: Any) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "translation_group": uuid,
        "status": "published",
        "data": {"title": title, "score": score, **extra},
    }


def link(uuid: str) -> dict[str, str]:
    return {"type": POST, "uuid": uuid}


async def import_rows(client: AsyncClient, tenant: str, key: str, rows: list[dict]) -> None:
    resp = await client.post(
        f"{API}/{key}/records/import?dry_run=false",
        content=json.dumps({"records": rows}),
        headers={**as_(tenant), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == len(rows), resp.text


async def make_type(client: AsyncClient, tenant: str, key: str) -> None:
    body = {
        "key": key,
        "label": f"{tenant} {key}",
        "fields": FIELDS if key == POST else FIELDS[:2],
        "display_field": "title",
        "slug_field": "title",
        "is_public": True,
        "translatable": True,
    }
    resp = await client.post(API, json=body, headers=as_(tenant))
    assert resp.status_code == 201, resp.text


async def seed(client: AsyncClient) -> None:
    """The two tenants of the module docstring, over the real API."""
    for tenant in (ACME, GLOBEX):
        await make_type(client, tenant, POST)
        same = row(SAME, f"{tenant} same", 1) | {"slug": "hello"}
        await import_rows(client, tenant, POST, [same])
    await import_rows(
        client,
        ACME,
        POST,
        [row(ACME_ONLY, "acme only", 10, link=link(SAME)), row(ACME_TRASHED, "acme bin", 11)],
    )
    trashed = await client.delete(f"{API}/{POST}/records/{ACME_TRASHED}", headers=as_(ACME))
    assert trashed.status_code == 204, trashed.text
    german = await client.post(
        f"{API}/{POST}/records/{SAME}/translations", json={"locale": "de"}, headers=as_(ACME)
    )
    assert german.status_code == 201, german.text
    await make_type(client, ACME, SECRET)
    await import_rows(client, ACME, SECRET, [row(ACME_SECRET, "acme secret", 5)])
    await import_rows(client, GLOBEX, POST, [row(GLOBEX_REF, "globex ref", 3, link=link(SAME))])


@pytest_asyncio.fixture
async def two_tenants(tmp_path) -> AsyncIterator[AsyncClient]:
    """A multi-tenant app holding the two tenants of the module docstring.

    Asserts on the way out that nothing ``acme`` owns changed, whatever the
    test did as ``globex``: that is the "cannot update, delete, restore,
    purge, roll back, bulk-act on" half of every case, checked for all of
    them at once."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    services = getattr(app.state, constants.PACKAGE)
    boot.mount_public_router(app, services.settings)
    services.settings = RecordsSettings(content_locales=("en", "de"), default_content_locale="en")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = db_state  # type: ignore[attr-defined]
        await seed(client)
        before = await tenant_rows(db_state)
        yield client
        assert await tenant_rows(db_state) == before, "a globex request changed acme's rows"
    await db_state.engine.dispose()


# --- no oracle ---------------------------------------------------------------------


_TIMING = re.compile(r'"duration_ms":\s*\d+')


def _normalised(response: Response, probes: dict[str, Any]) -> tuple[int, str]:
    text = _TIMING.sub('"duration_ms":0', response.text)
    for name, value in probes.items():
        text = text.replace(str(value), f"<{name}>")
    return response.status_code, text


async def same_as_unknown(
    client: AsyncClient,
    method: str,
    template: str,
    foreign: dict[str, Any],
    unknown: dict[str, Any],
    *,
    headers: dict[str, str],
    body: Callable[[dict[str, Any]], Any] | None = None,
    status: int = 404,
) -> Response:
    """``globex`` asking for ``acme``'s thing gets exactly what asking for
    nothing gets — the status and the body, each probe replaced by its name."""
    answers = []
    for probes in (foreign, unknown):
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["json"] = body(probes)
        answers.append(await client.request(method, template.format(**probes), **kwargs))
    got, want = (_normalised(r, p) for r, p in zip(answers, (foreign, unknown), strict=True))
    assert got == want, f"{method} {template}: {got} != {want}"
    assert got[0] == status, got
    return answers[0]


# --- acme is untouched ---------------------------------------------------------------


async def tenant_rows(db_state: Any, tenant: str = ACME) -> list[tuple]:
    """Every row ``tenant`` owns, and every index row of its records: what no
    ``globex`` request may change. Core selects with the predicate spelled
    out, so the census sees ``tenant_id`` and the guard does not apply."""
    out: list[tuple] = []
    async with db_state.session_factory() as session:
        type_table = RecordType.__table__
        types = select(type_table).where(type_table.c.tenant_id == tenant).order_by(type_table.c.id)
        out += [tuple(r) for r in (await session.execute(types)).all()]
        for tables in table_sets():
            ids: list[int] = []
            for cls in (tables.record, tables.revision):
                table = cls.__table__
                stmt = select(table).where(table.c.tenant_id == tenant).order_by(table.c.id)
                rows = (await session.execute(stmt)).all()
                out += [tuple(r) for r in rows]
                if cls is tables.record:
                    ids = [r.id for r in rows]
            for index in tables.index_tables:
                table = index.__table__
                stmt = select(table).where(table.c.record_id.in_(ids)).order_by(*table.c)
                out += [tuple(r) for r in (await session.execute(stmt)).all()]
    return out


# --- the route table ---------------------------------------------------------------

COVERED: set[tuple[str, str]] = set()


def covers(*routes: str) -> Callable[[Any], Any]:
    """``@covers("GET /api/records/types/{key}")`` — this test is that route's
    isolation case."""

    def mark(fn: Any) -> Any:
        for route in routes:
            method, path = route.split(" ", 1)
            COVERED.add((method, path))
        return fn

    return mark


def route_table() -> list[tuple[str, str]]:
    """``(method, path)`` for every route the module mounts, through the same
    hooks the host calls (``register_routes``, ``boot.mount_public_router``)."""
    module = RecordsModule()
    module.settings = RecordsSettings()
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    api_router = APIRouter(prefix=module.meta.route_prefix)
    view_router = APIRouter(prefix=module.meta.view_prefix)
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)
    boot.mount_public_router(app, module.settings)
    prefixes = (module.meta.route_prefix, module.meta.view_prefix)
    return sorted(
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        if route.path and route.path.startswith(prefixes)
        for method in route.methods or ()
    )
