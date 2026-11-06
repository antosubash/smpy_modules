"""Helpers for the import API tests: a multipart upload and the usual headers."""

from __future__ import annotations

from typing import Any

from sm_newsletter.core import constants

from tests.imports.fixtures import csv_bytes
from tests.imports.world import HEAD
from tests.support.import_world import SUB

API = constants.ROUTE_PREFIX_API
IMPORTS = f"{API}/imports"
MANAGE = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_MANAGE}"}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}


def csv_part(name: str, rows: list[list[str]], headers: list[str] | None = None):
    return ("files", (name, csv_bytes(headers or HEAD, rows), "text/csv"))


def raw_part(name: str, data: bytes):
    return ("files", (name, data, "application/octet-stream"))


async def upload(client: Any, *parts: Any, key: str = "news", headers: dict | None = None):
    return await client.post(
        IMPORTS, data={"list": key}, files=list(parts), headers=headers or MANAGE
    )


async def upload_ok(client: Any, rows: list[list[str]] | None = None) -> dict:
    rows = rows or [["a@example.org", "Ada", "L", "VIP"], ["b@example.org", "Bob", "", ""]]
    res = await upload(client, csv_part(SUB, rows))
    assert res.status_code == 201, res.text
    return res.json()
