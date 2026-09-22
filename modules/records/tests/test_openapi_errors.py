"""MISSING 6: the schema documents the refusals, and cannot drift from the docs.

`GET /openapi.json` rendered every records operation with correct request and
response models and **only** `200`/`201`/`204` plus FastAPI's own `422`. None
of the reference's error table appeared, so a generated client saw none of the
`400`/`403`/`404`/`409`/`413` contract and had to discover it by being
refused. Three operations had no `200` model at all, and `…/records/export`
declared `application/json` for a route that also serves `text/csv`.

Two halves, and the second is the one that keeps this true next year:

* every operation lists the statuses its kind of route can produce, and every
  status it lists is one the reference documents;
* the reference's error table *is* `_error_table.ERROR_TABLE`, cell for cell
  and in order — so neither can move without the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest_asyncio
from sm_records.endpoints.api._error_table import ERROR_TABLE

_DOC = Path(__file__).resolve().parents[1] / "docs" / "api-reference.md"
_API = "/api/records"
_PUBLIC = "/api/records/public"
_SUCCESS = {"200", "201", "202", "204"}
_ADMIN_MINIMUM = {"401", "403", "404", "500"}
_PUBLIC_MINIMUM = {"400", "404"}


@pytest_asyncio.fixture
async def schema(client):
    """The schema of an app whose ``on_startup`` has run, so the anonymous
    router — mounted from the lifespan hook — is in it too."""
    await client.app.state.records_module.on_startup(client.app)
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _operations(schema: dict, *, public: bool):
    for path, methods in schema["paths"].items():
        if not path.startswith(_API):
            continue
        if path.startswith(_PUBLIC) is not public:
            continue
        for method, operation in methods.items():
            yield f"{method.upper()} {path}", operation


def _doc_rows() -> list[tuple[int, str, str]]:
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index("| Status | When | Body |")
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("| `"):
            break
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        rows.append((int(cells[0].strip("`")), cells[1], cells[2]))
    return rows


# --- the schema ------------------------------------------------------------


async def test_every_admin_operation_documents_its_refusals(schema):
    for name, operation in _operations(schema, public=False):
        codes = set(operation.get("responses", {}))
        assert codes >= _ADMIN_MINIMUM, f"{name} documents {sorted(codes)}"


async def test_every_public_operation_documents_its_refusals(schema):
    """And documents **no** 401 or 403: the anonymous surface needs no session,
    and a type it will not serve is the same 404 as one that does not exist."""
    seen = list(_operations(schema, public=True))
    assert seen, "the anonymous router is not in the schema"
    for name, operation in seen:
        codes = set(operation.get("responses", {}))
        assert codes >= _PUBLIC_MINIMUM, f"{name} documents {sorted(codes)}"
        assert not codes & {"401", "403"}, f"{name} documents an auth refusal"


async def test_no_operation_documents_an_undocumented_status(schema):
    known = {str(row.status) for row in ERROR_TABLE} | _SUCCESS
    for name, operation in _operations(schema, public=True):
        assert set(operation["responses"]) <= known, name
    for name, operation in _operations(schema, public=False):
        assert set(operation["responses"]) <= known, name


async def test_every_refusal_names_a_body_schema(schema):
    """A status with a description and no schema is a status a generated
    client cannot parse."""
    for name, operation in _operations(schema, public=False):
        for code, spec in operation["responses"].items():
            if code in _SUCCESS or code == "204":
                continue
            assert spec.get("content"), f"{name} {code} has no body schema"


async def test_the_three_operations_that_had_no_response_model_have_one(schema):
    export = schema["paths"][f"{_API}/types/{{key}}/records/export"]["get"]
    assert set(export["responses"]["200"]["content"]) == {"application/json", "text/csv"}

    preview = schema["paths"][f"{_API}/types/{{key}}/schema/preview"]["post"]
    assert preview["responses"]["200"]["content"]["application/json"]["schema"]
    assert preview["responses"]["202"]["content"]["application/json"]["schema"]

    reindex = schema["paths"][f"{_API}/types/{{key}}/reindex"]["post"]
    assert reindex["responses"]["202"]["content"]["application/json"]["schema"]


# --- the documentation -----------------------------------------------------


def test_the_reference_error_table_is_the_shared_table():
    """Cell for cell, in order. If this fails, one of the two moved — fix the
    one that is wrong, and they go back to being one description."""
    assert _doc_rows() == [tuple(row) for row in ERROR_TABLE]


def test_every_status_in_the_table_has_a_body_model():
    from sm_records.endpoints.api._responses import _MODELS

    assert {row.status for row in ERROR_TABLE} <= set(_MODELS)
