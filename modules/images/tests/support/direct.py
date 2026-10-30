"""Direct-upload helpers shared by the upload tests: start, relay the parts,
complete, and a part size that splits a test-sized image in two."""

from __future__ import annotations

import pytest
from sm_images import constants

from tests.support.upload import BASE, OLGA

UPLOADS = "/api/images/uploads"


async def start(client, cid, data: bytes, headers=OLGA, **extra):
    body = {"filename": "big.jpg", "size": len(data), **extra}
    return await client.post(f"{BASE}/{cid}/uploads", json=body, headers=headers)


async def send_parts(client, created: dict, data: bytes, headers=OLGA) -> list[dict]:
    size = created["part_size"]
    parts = []
    for n, url in enumerate(created["part_urls"], start=1):
        chunk = data[(n - 1) * size : n * size]
        put = await client.put(url, content=chunk, headers=headers)
        assert put.status_code == 200, put.text
        parts.append({"no": n, "etag": put.json()["etag"]})
    return parts


async def complete(client, upload_id: str, parts, headers=OLGA, **body):
    return await client.post(
        f"{UPLOADS}/{upload_id}/complete", json={"parts": parts, **body}, headers=headers
    )


@pytest.fixture
def small_parts(monkeypatch):
    """Two parts for a test-sized image."""
    monkeypatch.setattr(constants, "DIRECT_PART_BYTES", 400)
