"""``/imports`` over HTTP: upload, preview, mapping, apply, discard, errors CSV."""

from __future__ import annotations

import csv
import io

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.imports import launch as launch_mod

from tests.imports.fixtures import csv_bytes, zip_bytes
from tests.imports.world import FIELDS, HEAD
from tests.support.app import build_app
from tests.support.import_http import (
    IMPORTS,
    MANAGE,
    csv_part,
    raw_part,
    upload,
    upload_ok,
)
from tests.support.import_world import SUB, UNSUB
from tests.support.records_seed import seed_list


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    app, state = await build_app(file=tmp_path / "imports.db")
    await seed_list(state, "default", "news", fields=FIELDS)
    monkeypatch.setattr(launch_mod, "celery_eager", lambda: True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await state.engine.dispose()


async def test_upload_zip_then_preview(client):
    rows = [["a@example.org", "Ada", "L", "VIP"], ["b@example.org", "Bob", "", "VIP,Early"]]
    archive = zip_bytes(
        {SUB: csv_bytes(HEAD, rows), UNSUB: csv_bytes(HEAD, [["c@example.org", "", "", ""]])}
    )
    res = await upload(client, raw_part("export.zip", archive))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "staged" and body["list_type_key"] == "news"
    assert (body["total"], body["duplicates"], body["invalid"]) == (3, 0, 0)
    assert [(f["name"], f["kind"], f["rows"]) for f in body["files"]] == [
        (SUB, "subscribed", 2),
        (UNSUB, "unsubscribed", 1),
    ]
    assert [c["header"] for c in body["columns"]] == ["First Name", "Last Name"]
    assert {t["label"]: t["count"] for t in body["tags_found"]} == {"VIP": 2, "Early": 1}
    assert body["mapping"]["fields"] == {"0": "first_name", "1": "last_name"}
    assert body["mapping"]["tags"] is True
    assert {f["key"] for f in body["targets"]["fields"]} >= {"first_name", "last_name"}
    assert body["targets"]["tags"] in ("present", "creatable")
    assert body["errors"] == [] and body["errors_total"] == 0
    got = await client.get(f"{IMPORTS}/{body['id']}", headers=MANAGE)
    assert got.json() == body
    listed = (await client.get(IMPORTS, headers=MANAGE)).json()
    assert [(j["id"], j["status"], j["total"]) for j in listed] == [(body["id"], "staged", 3)]


async def test_upload_three_csv_parts(client):
    res = await upload(
        client,
        csv_part(SUB, [["a@example.org", "A", "", ""]]),
        csv_part("p2.csv", [["b@example.org", "B", "", ""]]),
        csv_part("p3.csv", [["a@example.org", "A", "", ""]]),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert len(body["files"]) == 3
    assert (body["total"], body["duplicates"]) == (2, 1)


async def test_patch_mapping_round_trip_and_bad_mapping_422(client):
    job = await upload_ok(client)
    url = f"{IMPORTS}/{job['id']}"
    new = {"fields": {"1": "first_name"}, "tags": False}
    res = await client.patch(url, json={"mapping": new}, headers=MANAGE)
    assert res.status_code == 200, res.text
    assert res.json()["mapping"] == new
    assert (await client.get(url, headers=MANAGE)).json()["mapping"] == new
    for bad in (
        {"fields": {"9": "first_name"}, "tags": False},
        {"fields": {"1": "nope"}, "tags": False},
        {"fields": {"0": "first_name", "1": "first_name"}, "tags": False},
        "x",
    ):
        res = await client.patch(url, json={"mapping": bad}, headers=MANAGE)
        assert (res.status_code, res.json()["code"]) == (422, "import_bad_mapping"), bad
    assert (await client.patch(url, json={"nope": 1}, headers=MANAGE)).status_code == 422
    assert (await client.get(url, headers=MANAGE)).json()["mapping"] == new


async def test_apply_eager_runs_to_done(client):
    job = await upload_ok(client)
    res = await client.post(f"{IMPORTS}/{job['id']}/apply", json={}, headers=MANAGE)
    assert res.status_code == 202, res.text
    polled = (await client.get(f"{IMPORTS}/{job['id']}", headers=MANAGE)).json()
    assert polled["status"] == "done"
    assert (polled["created"], polled["failed"], polled["processed"]) == (2, 0, 2)
    assert res.json()["status"] in ("queued", "running", "done")


async def test_apply_twice_is_409(client):
    job = await upload_ok(client)
    url = f"{IMPORTS}/{job['id']}/apply"
    assert (await client.post(url, json={}, headers=MANAGE)).status_code == 202
    again = await client.post(url, json={}, headers=MANAGE)
    assert (again.status_code, again.json()["code"]) == (409, "import_not_staged")


async def test_discard_then_404(client):
    job = await upload_ok(client)
    url = f"{IMPORTS}/{job['id']}"
    assert (await client.delete(url, headers=MANAGE)).status_code == 204
    assert (await client.get(url, headers=MANAGE)).status_code == 404
    assert (await client.delete(url, headers=MANAGE)).status_code == 404
    assert (await client.get(IMPORTS, headers=MANAGE)).json() == []


async def test_discard_with_stale_status_is_409_and_keeps_the_import(client):
    job = await upload_ok(client)
    url = f"{IMPORTS}/{job['id']}"
    assert (await client.post(f"{url}/apply", json={}, headers=MANAGE)).status_code == 202
    stale = await client.delete(url, params={"status": "staged"}, headers=MANAGE)
    assert (stale.status_code, stale.json()["code"]) == (409, "import_changed")
    assert (await client.get(url, headers=MANAGE)).status_code == 200
    bad = await client.delete(url, params={"status": "bogus"}, headers=MANAGE)
    assert bad.status_code == 422
    assert (await client.delete(url, params={"status": "done"}, headers=MANAGE)).status_code == 204
    assert (await client.get(url, headers=MANAGE)).status_code == 404


async def test_errors_csv_neutralises_formulas(client):
    name = "=cmd.csv"
    head = ["Email Address", "=HYPERLINK(1)"]
    res = await upload(
        client,
        csv_part(name, [["not-an-email", "x"], ["ok@example.org", "y"]], headers=head),
    )
    assert res.status_code == 201, res.text
    job = res.json()
    assert [e["code"] for e in job["errors"]] == ["invalid_email"]
    got = await client.get(f"{IMPORTS}/{job['id']}/errors.csv", headers=MANAGE)
    assert got.status_code == 200
    assert got.headers["content-type"] == "text/csv; charset=utf-8"
    assert got.headers["cache-control"] == "no-store"
    assert got.headers["content-disposition"] == (
        f'attachment; filename="import-{job["id"]}-errors.csv"'
    )
    rows = list(csv.reader(io.StringIO(got.text)))
    assert rows[0] == ["file", "file_name", "line", "code", "field"]
    assert rows[1][:2] == ["0", "'=cmd.csv"]
    assert rows[1][3] == "invalid_email"
    assert all(not c.startswith(("=", "+", "-", "@")) for r in rows for c in r)
    assert rows[1][2] == "2"  # line number stays numeric
    assert got.text.splitlines()[1].startswith('"0","\'=cmd.csv"')
