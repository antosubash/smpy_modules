"""Shared setup for test_i18n_public."""

from __future__ import annotations
import json
import pytest_asyncio
from sqlalchemy import event
from tests.support.app_harness import ADMIN, roles
from tests.support.i18n_helpers import API, TYPE_KEY, make_record, make_type, publish, translate
from tests.support.i18n_helpers import use_locales as _use_locales

PREFIX = "/api/records/public"


@pytest_asyncio.fixture
async def site(client):
    """A two-language install with the public router mounted, as the host's
    own ``on_startup`` mounts it (its prefix is a DB-backed setting)."""
    _use_locales(client, "en", "de")
    await client.app.state.records_module.on_startup(client.app)
    await make_type(client, is_public=True)
    return client


async def _published_pair(site, title: str = "About us") -> tuple[dict, dict]:
    """An English record and its published German sibling, sharing a group."""
    english = await publish(site, await make_record(site, title))
    german = (await translate(site, english["uuid"], "de")).json()
    return english, await publish(site, german)


async def _export(client, fmt: str) -> str:
    resp = await client.get(f"{API}/{TYPE_KEY}/records/export?format={fmt}", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return resp.text


async def _import(client, text: str, fmt: str, **params):
    return await client.post(
        f"{API}/{TYPE_KEY}/records/import",
        content=text.encode(),
        headers={**roles(ADMIN), "Content-Type": "application/json"},
        params={"format": fmt, "dry_run": "false", **params},
    )
