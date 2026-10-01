"""MAJOR 1: the two integer overflows that were 500s, at their exact edges.

``Record.position`` is a 32-bit column and an ``integer`` field indexes into
the same ``Numeric(19, 5)`` column a ``number`` field does — but neither bound
was stated anywhere, and Python integers have no ceiling of their own, so
``position = 2**31`` and a ``count`` of ``10**14`` both reached the driver and
came back as ``DataError``/``NumericValueOutOfRangeError``: a 500 for a value
the ``number`` type already refused with a clean 422 naming the digits.

The boundaries are asserted exactly, in pairs: the largest accepted value and
the smallest refused one, on every write path that can set either.
"""

from __future__ import annotations

import json

from sm_records.constants import MAX_POSITION, MIN_POSITION
from sm_records.schema._scalars import MAX_INT_DIGITS

from tests.app_harness import ADMIN, api_type, roles

_API = "/api/records/types"
_FIELDS = [
    {"key": "name", "type": "text", "label": "Name", "indexed": True},
    {"key": "count", "type": "integer", "label": "Count", "indexed": True},
]


async def _type(client, key: str) -> dict:
    return await api_type(client, key, _FIELDS, display_field="name")


async def _create(client, key: str, body: dict):
    return await client.post(f"{_API}/{key}/records", json=body, headers=roles(ADMIN))


# --- position --------------------------------------------------------------


async def test_position_at_the_int32_edges_is_accepted(client):
    await _type(client, "posok")
    for position in (MAX_POSITION, MIN_POSITION, 0):
        resp = await _create(
            client, "posok", {"data": {"name": str(position)}, "position": position}
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["position"] == position


async def test_position_one_past_either_edge_is_a_422_naming_the_field(client):
    await _type(client, "posbad")
    for position in (MAX_POSITION + 1, MIN_POSITION - 1, 2**63, -(10**20)):
        resp = await _create(client, "posbad", {"data": {"name": "x"}, "position": position})
        assert resp.status_code == 422, (position, resp.text)
        assert resp.json()["errors"][0]["field"] == "position"


async def test_position_is_bounded_on_update_too(client):
    await _type(client, "posupd")
    created = await _create(client, "posupd", {"data": {"name": "x"}})
    assert created.status_code == 201, created.text
    resp = await client.put(
        f"{_API}/posupd/records/{created.json()['uuid']}",
        json={"data": {"name": "x"}, "expected_version": 1, "position": MAX_POSITION + 1},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "position"


async def test_an_out_of_range_position_is_one_import_row_error(client):
    await _type(client, "posimp")
    document = {
        "records": [
            {"data": {"name": "fine"}, "position": 1},
            {"data": {"name": "huge"}, "position": MAX_POSITION + 1},
        ]
    }
    resp = await client.post(
        f"{_API}/posimp/records/import?dry_run=false&format=json&on_error=skip",
        content=json.dumps(document),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["created"] == 1
    assert report["failed"] == 1
    assert report["errors"][0]["row"] == 2


# --- integer fields --------------------------------------------------------


async def test_an_integer_field_at_the_digit_limit_is_stored_and_filterable(client):
    await _type(client, "intok")
    value = 10 ** (MAX_INT_DIGITS - 1)
    assert len(str(value)) == MAX_INT_DIGITS
    resp = await _create(client, "intok", {"data": {"name": "big", "count": value}})
    assert resp.status_code == 201, resp.text
    listed = await client.get(f"{_API}/intok/records?filter=count:eq:{value}", headers=roles(ADMIN))
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1


async def test_an_integer_field_one_digit_over_is_a_422(client):
    await _type(client, "intbad")
    for value in (10**MAX_INT_DIGITS, -(10**MAX_INT_DIGITS), 2**63, 10**100):
        resp = await _create(client, "intbad", {"data": {"name": "x", "count": value}})
        assert resp.status_code == 422, (value, resp.text)
        assert resp.json()["errors"][0]["field"] == "count"
        assert "digits" in resp.json()["errors"][0]["message"]


async def test_an_integer_field_sent_as_a_string_is_bounded_the_same_way(client):
    await _type(client, "intstr")
    resp = await _create(
        client, "intstr", {"data": {"name": "x", "count": str(10**MAX_INT_DIGITS)}}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "count"
