"""Shared record test builders."""

from __future__ import annotations

from tests.support.app_harness import ADMIN, roles
from tests.support.app_harness import field as _field

_API = "/api/records/types"


async def _seed(client, count: int, *, key: str = "widget") -> None:
    body = {
        "key": key,
        "label": key.title(),
        "fields": [_field("name", "text")],
        "display_field": "name",
    }
    resp = await client.post("/api/records/types", json=body, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    for n in range(count):
        made = await client.post(
            f"{_API}/{key}/records",
            json={"data": {"name": f"item-{n:03d}"}},
            headers=roles(ADMIN),
        )
        assert made.status_code == 201, made.text
