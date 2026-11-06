"""``/imports``: permissions, CSRF, list narrowing, tenants, size and refusals that never echo."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from sm_newsletter.imports import archive
from sm_newsletter.imports import launch as launch_mod

from tests.imports.fixtures import csv_bytes, zip_bytes
from tests.imports.world import FIELDS, HEAD
from tests.support.app import build_app
from tests.support.import_http import (
    EDIT,
    IMPORTS,
    MANAGE,
    csv_part,
    raw_part,
    upload,
    upload_ok,
)
from tests.support.import_world import SUB
from tests.support.records_seed import restrict_list, seed_list

SENTINEL = "sentinel-7f3a"


@pytest_asyncio.fixture
async def built(tmp_path, monkeypatch):
    app, state = await build_app(file=tmp_path / "guards.db")
    await seed_list(state, "default", "news", fields=FIELDS)
    monkeypatch.setattr(launch_mod, "celery_eager", lambda: True)
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_permissions(client):
    job = await upload_ok(client)
    url = f"{IMPORTS}/{job['id']}"
    calls = [
        ("GET", IMPORTS, {}),
        ("GET", url, {}),
        ("PATCH", url, {"json": {"mapping": {}}}),
        ("POST", f"{url}/apply", {"json": {}}),
        ("DELETE", url, {}),
        ("GET", f"{url}/errors.csv", {}),
        ("POST", IMPORTS, {"data": {"list": "news"}, "files": [csv_part(SUB, [])]}),
    ]
    for method, path, kw in calls:
        res = await client.request(method, path, headers=EDIT, **kw)
        assert res.status_code == 403, (method, path)
    assert (await client.get(url, headers=MANAGE)).status_code == 200


async def test_csrf_required_on_writes():
    app, state = await build_app(session=True)
    try:
        await seed_list(state, "default", "news", fields=FIELDS)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            token = (await c.get("/token")).json()["token"]
            parts = {"data": {"list": "news"}, "files": [csv_part(SUB, [["a@example.org"] * 4])]}
            refused = await c.post(IMPORTS, headers=MANAGE, **parts)
            assert refused.status_code == 403
            ok = await c.post(IMPORTS, headers={**MANAGE, CSRF_HEADER: token}, **parts)
            assert ok.status_code == 201, ok.text
            url = f"{IMPORTS}/{ok.json()['id']}"
            assert (await c.delete(url, headers=MANAGE)).status_code == 403
            assert (await c.post(f"{url}/apply", json={}, headers=MANAGE)).status_code == 403
            patch = await c.patch(url, json={"mapping": {}}, headers=MANAGE)
            assert patch.status_code == 403
            assert (await c.get(url, headers=MANAGE)).status_code == 200
    finally:
        await state.engine.dispose()


async def test_restricted_list_404(built, client):
    _, state = built
    job = await upload_ok(client)
    await restrict_list(state, "default", "news", ["editor"])
    url = f"{IMPORTS}/{job['id']}"
    assert (await upload(client, csv_part(SUB, [["a@example.org"] * 4]))).status_code == 404
    for method, path in (
        ("GET", url),
        ("DELETE", url),
        ("GET", f"{url}/errors.csv"),
        ("POST", f"{url}/apply"),
    ):
        res = await client.request(method, path, headers=MANAGE)
        assert res.status_code == 404, (method, path)
    assert (await client.get(IMPORTS, headers=MANAGE)).json() == []
    allowed = {**MANAGE, "x-roles": "editor"}
    assert (await client.get(url, headers=allowed)).status_code == 200


@pytest.mark.unbound_tenant
async def test_other_tenants_import_404(client):
    job = await upload_ok(client)
    other = {**MANAGE, "x-tenant": "other"}
    url = f"{IMPORTS}/{job['id']}"
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.delete(url, headers=other)).status_code == 404
    assert (await client.get(IMPORTS, headers=other)).json() == []


async def test_unknown_or_missing_list_404(client):
    part = csv_part(SUB, [["a@example.org"] * 4])
    assert (await upload(client, part, key="nope")).status_code == 404
    res = await client.post(IMPORTS, files=[part], headers=MANAGE)
    assert res.status_code == 404


async def test_upload_over_limit_413(client, monkeypatch):
    monkeypatch.setattr(archive, "MAX_ENTRY_BYTES", 10)
    res = await upload(client, csv_part(SUB, [["a@example.org", "Ada", "", ""]]))
    assert (res.status_code, res.json()["code"]) == (413, "import_too_large")


def test_body_limit_is_registered_for_the_upload_only():
    from simple_module_core.body_limits import BodyLimitRegistry
    from sm_newsletter.imports.constants import MAX_UPLOAD_BYTES, MiB
    from sm_newsletter.module import NewsletterModule

    registry = BodyLimitRegistry()
    NewsletterModule().register_body_limits(registry)
    assert registry.limit_for("POST", f"{IMPORTS}") == MAX_UPLOAD_BYTES + MiB
    assert registry.limit_for("POST", f"{IMPORTS}/") == MAX_UPLOAD_BYTES + MiB
    assert registry.limit_for("GET", IMPORTS) is None
    assert registry.limit_for("POST", f"{IMPORTS}/1/apply") is None


def _refusals():
    wide = [f"{SENTINEL}{i}" for i in range(201)]
    encrypted = zip_bytes({f"{SENTINEL}.csv": csv_bytes(HEAD, [])}, flag_bits=0x1)
    return {
        "not_csv": [raw_part(f"{SENTINEL}.txt", b"hello")],
        "no_email": [csv_part(f"{SENTINEL}.csv", [[SENTINEL]], headers=[SENTINEL])],
        "bad_utf8": [
            raw_part(f"{SENTINEL}.csv", b"Email Address\n" + SENTINEL.encode() + b"\xff\n")
        ],
        "too_many_columns": [csv_part(f"{SENTINEL}.csv", [], headers=["Email Address", *wide])],
        "encrypted_zip": [raw_part(f"{SENTINEL}.zip", encrypted)],
        "bad_zip": [raw_part(f"{SENTINEL}.zip", SENTINEL.encode())],
        "too_many_files": [csv_part(f"{SENTINEL}{i}.csv", [[SENTINEL] * 4]) for i in range(5)],
    }


@pytest.mark.parametrize("case", list(_refusals()))
async def test_refusals_do_not_echo(client, case):
    res = await upload(client, *_refusals()[case])
    assert 400 <= res.status_code < 500, res.text
    assert SENTINEL not in res.text
    assert "code" in res.json()
    assert (await client.get(IMPORTS, headers=MANAGE)).json() == []  # nothing was staged


async def test_bad_mapping_does_not_echo(client):
    job = await upload_ok(client)
    res = await client.patch(
        f"{IMPORTS}/{job['id']}",
        json={"mapping": {"fields": {"0": SENTINEL}, "tags": False}},
        headers=MANAGE,
    )
    assert res.status_code == 422 and SENTINEL not in res.text
