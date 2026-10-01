"""MAJOR 2 / MINOR 3: each router answers in the language its callers speak.

Two halves of one route class, and each was wrong for the other's caller:

* the Inertia screens under ``/admin/records/*`` answered a browser with a raw
  JSON body on a 404 — a stale bookmark, a renamed type or a record purged in
  another tab dumped a blob into the window, while a FastAPI validation error
  on the *same* screen rendered HTML;
* the JSON API let every unanticipated exception fall through to the host's
  handler, which serves the SPA document regardless of ``Accept`` — so a
  client that asked for JSON got 42 KB of HTML and a decode error instead of a
  status it could act on, and the request's session was never rolled back.
"""

from __future__ import annotations

import pytest

from tests.app_harness import ADMIN, api_type, roles

_API = "/api/records/types"
_ADMIN = "/admin/records"
_FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def _type(client, key: str) -> dict:
    return await api_type(client, key, _FIELDS, display_field="name")


# --- the view router: an error page, not a JSON blob ----------------------


@pytest.mark.parametrize(
    "path",
    [
        "/nosuchtype",
        "/nosuchtype/deadbeefdeadbeefdeadbeefdeadbeef",
        "/types/nosuchtype",
    ],
)
async def test_a_view_route_renders_the_frameworks_error_page(client, path):
    resp = await client.get(f"{_ADMIN}{path}", headers={**roles(ADMIN), "Accept": "text/html"})
    assert resp.status_code == 404, resp.text
    assert resp.headers["content-type"].startswith("text/html"), resp.headers["content-type"]


async def test_a_missing_record_on_a_real_type_is_an_error_page_too(client):
    await _type(client, "viewtype")
    resp = await client.get(
        f"{_ADMIN}/viewtype/{'0' * 32}", headers={**roles(ADMIN), "Accept": "text/html"}
    )
    assert resp.status_code == 404, resp.text
    assert resp.headers["content-type"].startswith("text/html")


async def test_a_working_view_route_is_untouched(client):
    await _type(client, "viewok")
    resp = await client.get(f"{_ADMIN}/viewok", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text


# --- the JSON router: JSON, whatever went wrong ---------------------------


async def test_an_unhandled_exception_on_the_api_is_json(client, monkeypatch):
    """Forced from the service the endpoint calls, so the failure is where a
    real one would be: inside the handler, after the dependencies resolved and
    the request's session was opened."""
    from sm_records.endpoints.api import types as types_endpoint

    async def boom(*_args, **_kwargs):
        raise RuntimeError("forced: a bug in a service")

    monkeypatch.setattr(types_endpoint.type_service, "list_types", boom)
    resp = await client.get(_API, headers={**roles(ADMIN), "Accept": "application/json"})
    assert resp.status_code == 500, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"detail": "internal error"}


async def test_an_unhandled_exception_rolls_the_request_session_back(client, monkeypatch):
    """The 500 must not commit what the failed handler had already written.

    ``create_type`` flushes the row before ``snapshot`` runs, so a failure
    there is a request that wrote and then blew up — exactly the shape the
    409 paths already roll back.
    """
    from sm_records.services import types as type_service

    async def boom(*_args, **_kwargs):
        raise RuntimeError("forced: after the row was flushed")

    monkeypatch.setattr(type_service, "snapshot", boom)
    resp = await client.post(
        _API,
        json={"key": "rolled", "label": "Rolled", "fields": _FIELDS},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 500, resp.text
    monkeypatch.undo()
    listed = await client.get(_API, headers=roles(ADMIN))
    assert listed.status_code == 200, listed.text
    assert [item["key"] for item in listed.json()["items"]] == []


async def test_a_mapped_error_on_the_api_is_still_its_own_status(client):
    """The catch-all must sit *after* the mapped branches, not swallow them."""
    resp = await client.get(f"{_API}/nosuchtype", headers=roles(ADMIN))
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "no record type with key 'nosuchtype'"


async def test_a_fastapi_validation_error_on_the_api_is_still_a_422(client):
    """``HTTPException`` and friends are re-raised, or every 400 the grammar
    produces would have become a 500."""
    await _type(client, "stillvalid")
    resp = await client.get(f"{_API}/stillvalid/records?page=0", headers=roles(ADMIN))
    assert resp.status_code == 422, resp.text
    bad_filter = await client.get(f"{_API}/stillvalid/records?filter=nope", headers=roles(ADMIN))
    assert bad_filter.status_code == 400, bad_filter.text
