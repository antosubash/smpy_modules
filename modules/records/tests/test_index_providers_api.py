"""Virtual fields over HTTP: a provider-projected key filters and sorts on
``/api/records/types/{key}/records`` exactly as a declared indexed field does,
and is refused as a declared field key with a 422 that names it.

The provider itself and the registry rules live in ``test_index_providers.py``;
this file is the half that goes through the real router, the real write path
and the real query parser (``deps.parse_filters``' ``field:op:value``).
"""

from __future__ import annotations

import pytest
from sm_records.index import register_index_provider
from sm_records.models import IndexNumber, IndexText
from sqlalchemy import select

from tests.app_harness import ADMIN, roles
from tests.app_harness import field as _field
from tests.test_index_providers import BUCKET, TAGS_UPPER, VIRTUAL_FIELDS, sample_provider

_CHOICES = [{"value": tag, "label": tag.title()} for tag in ("red", "blue")]


@pytest.fixture
async def catalogue(client):
    """A ``product`` type and three records, created through the API so the
    rows come from the same write path production uses."""
    register_index_provider(sample_provider, fields=VIRTUAL_FIELDS)
    body = {
        "key": "product",
        "label": "Product",
        "fields": [
            _field("name", "text"),
            _field("price", "number"),
            _field("tags", "multiselect", choices=_CHOICES),
        ],
    }
    created = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert created.status_code == 201
    for name, price, tags in (
        ("cheap", 50, ["red"]),
        ("mid", 150, ["red", "blue"]),
        ("dear", 250, ["blue"]),
    ):
        resp = await client.post(
            "/api/records/types/product/records",
            json={"data": {"name": name, "price": price, "tags": tags}},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 201
    return client


async def names(client, *params) -> list[str]:
    resp = await client.get(
        "/api/records/types/product/records", params=list(params), headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    return [item["data"]["name"] for item in resp.json()["items"]]


async def test_filter_eq_on_a_virtual_number_field(catalogue):
    assert await names(catalogue, ("filter", f"{BUCKET}:eq:2")) == ["dear"]


async def test_filter_gte_on_a_virtual_number_field(catalogue):
    assert sorted(await names(catalogue, ("filter", f"{BUCKET}:gte:1"))) == ["dear", "mid"]


async def test_sort_by_a_virtual_field_both_ways(catalogue):
    assert await names(catalogue, ("sort", BUCKET)) == ["cheap", "mid", "dear"]
    assert await names(catalogue, ("sort", f"-{BUCKET}")) == ["dear", "mid", "cheap"]


async def test_eq_on_a_many_virtual_field_is_any_of(catalogue):
    assert sorted(await names(catalogue, ("filter", f"{TAGS_UPPER}:eq:RED"))) == ["cheap", "mid"]


async def test_ne_on_a_many_virtual_field_is_none_of(catalogue):
    """``mid`` holds RED *and* BLUE, so "some value differs" would match it —
    which is not what anybody asking for ``ne`` means."""
    assert await names(catalogue, ("filter", f"{TAGS_UPPER}:ne:RED")) == ["dear"]


async def test_an_unknown_key_is_still_a_400(catalogue):
    resp = await catalogue.get(
        "/api/records/types/product/records",
        params=[("filter", "no_such_key:eq:1")],
        headers=roles(ADMIN),
    )
    assert resp.status_code == 400
    assert resp.json()["reason"] == "unknown"


async def test_declaring_a_virtual_key_as_a_field_is_422(client):
    """The editor cannot know what the host registered, so this is a 422 with
    a message that names the key — not a greyed-out input."""
    register_index_provider(sample_provider, fields=VIRTUAL_FIELDS)
    resp = await client.post(
        "/api/records/types",
        json={"key": "widget", "label": "Widget", "fields": [_field(BUCKET, "number")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    error = resp.json()["errors"][0]
    assert error["field"] == BUCKET
    assert "index provider" in error["message"]


async def test_purge_removes_the_provider_s_rows(catalogue, records_app):
    _app, db_state = records_app
    listed = await catalogue.get(
        "/api/records/types/product/records",
        headers=roles(ADMIN),
        params=[("filter", f"{BUCKET}:eq:2")],
    )
    uuid = listed.json()["items"][0]["uuid"]

    assert (
        await catalogue.delete(f"/api/records/types/product/records/{uuid}", headers=roles(ADMIN))
    ).status_code == 204
    assert (
        await catalogue.delete(
            f"/api/records/types/product/records/{uuid}/purge", headers=roles(ADMIN)
        )
    ).status_code == 204

    async with db_state.session_factory() as session:
        buckets = (
            (await session.execute(select(IndexNumber).where(IndexNumber.field_key == BUCKET)))
            .scalars()
            .all()
        )
        tags = (
            (await session.execute(select(IndexText).where(IndexText.field_key == TAGS_UPPER)))
            .scalars()
            .all()
        )
    assert sorted(row.value for row in buckets) == [0, 1]
    assert sorted(row.value for row in tags) == ["BLUE", "RED", "RED"]
