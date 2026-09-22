"""MAJOR 3: an oversized write body is refused before it is read.

``max_payload_bytes`` is checked on the serialized payload, which is after
FastAPI has read and parsed the whole request — so a 64 MiB body was read,
decoded and pydantic-validated in order to produce a 422 about a 256 KiB
limit. The 422 was right; the cost was not, and a handful of concurrent
multi-hundred-megabyte bodies from one authenticated editor is an OOM on the
worker with no framework body guard behind it.

The assertion that matters is not the status: it is that **the handler was
never entered**. Each test below patches the endpoint's own service with a
recorder, so "did we pay for this refusal?" is a fact the test can read rather
than an inference from timing.
"""

from __future__ import annotations

import json

from sm_records._body_limit import ENVELOPE_HEADROOM, body_ceiling
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles

_API = "/api/records/types"
_FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]
_HUGE = 64 * 1024 * 1024
_CEILING = body_ceiling(RecordsSettings())


async def _type(client, key: str) -> dict:
    resp = await client.post(
        _API,
        json={"key": key, "label": key.title(), "fields": _FIELDS, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _tripwire(monkeypatch, module, name: str) -> list[int]:
    """Replace ``module.name`` with something that records being called."""
    entered: list[int] = []
    original = getattr(module, name)

    async def recording(*args, **kwargs):
        entered.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, name, recording)
    return entered


async def test_a_64_mib_record_write_is_refused_without_entering_the_handler(client, monkeypatch):
    await _type(client, "bodyrec")
    from sm_records.endpoints.api import records as records_endpoint

    entered = _tripwire(monkeypatch, records_endpoint.record_service, "create_record")
    resp = await client.post(
        f"{_API}/bodyrec/records",
        content=b"x" * 16,
        headers={
            **roles(ADMIN),
            "Content-Type": "application/json",
            "Content-Length": str(_HUGE),
        },
    )
    assert resp.status_code == 413, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert str(_HUGE) in resp.json()["detail"]
    assert entered == [], "the handler ran for a body this refusal never read"


async def test_the_same_guard_covers_a_type_write(client, monkeypatch):
    from sm_records.endpoints.api import types as types_endpoint

    entered = _tripwire(monkeypatch, types_endpoint.type_service, "create_type")
    resp = await client.post(
        _API,
        content=b"x" * 16,
        headers={
            **roles(ADMIN),
            "Content-Type": "application/json",
            "Content-Length": str(_HUGE),
        },
    )
    assert resp.status_code == 413, resp.text
    assert entered == []


async def test_a_body_with_no_content_length_is_refused_while_it_is_read(client, monkeypatch):
    """A chunked upload declares no length, so the header check cannot see it;
    the running total is what it cannot lie about."""
    await _type(client, "bodychunk")
    from sm_records.endpoints.api import records as records_endpoint

    entered = _tripwire(monkeypatch, records_endpoint.record_service, "create_record")

    async def chunks():
        payload = b"x" * (_CEILING + 1024)
        for start in range(0, len(payload), 65536):
            yield payload[start : start + 65536]

    resp = await client.post(
        f"{_API}/bodychunk/records",
        content=chunks(),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413, resp.text
    assert entered == []


async def test_an_ordinary_write_is_untouched(client):
    await _type(client, "bodyok")
    resp = await client.post(
        f"{_API}/bodyok/records", json={"data": {"name": "small"}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 201, resp.text


async def test_a_body_just_under_the_ceiling_still_reaches_its_own_422(client):
    """The ceiling is looser than ``max_payload_bytes`` on purpose: the route's
    own check is the contract, and it must still be the thing that answers."""
    await _type(client, "bodyedge")
    settings = RecordsSettings()
    oversized = "y" * (settings.max_payload_bytes + ENVELOPE_HEADROOM // 2)
    resp = await client.post(
        f"{_API}/bodyedge/records",
        json={"data": {"name": oversized}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422, resp.status_code
    assert "over the" in resp.json()["detail"]


async def test_the_import_route_keeps_its_own_larger_ceiling(client):
    """50 MB by default, and unreachable if the 320 KB guard applied here."""
    await _type(client, "bodyimp")
    filler = "p" * 200
    rows = [{"data": {"name": f"row-{index}-{filler}"}} for index in range(2000)]
    document = json.dumps({"records": rows}).encode()
    assert len(document) > _CEILING, len(document)
    resp = await client.post(
        f"{_API}/bodyimp/records/import?dry_run=true&format=json",
        content=document,
        headers={**roles(ADMIN), "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 2000
