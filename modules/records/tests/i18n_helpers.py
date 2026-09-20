"""A translatable type over HTTP, and the two-locale install to hold it.

Shared by the three content-i18n suites so each stays under the 300-line cap.

The settings object is swapped on ``app.state.sm_records`` rather than on the
module instance: that is where ``deps.get_settings`` reads it from on every
request (``CLAUDE.md``: env → DB → default, re-read per request), so a test
that pinned the module's copy instead would configure something nothing looks
at. It is also why these tests do not need a lifespan or a settings table.
"""

from __future__ import annotations

from typing import Any

from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, roles

TYPE_KEY = "article"
API = "/api/records/types"


def use_locales(client, *tags: str, default: str | None = None) -> RecordsSettings:
    """Reconfigure this app's content locales for the rest of the test."""
    settings = RecordsSettings(
        content_locales=tags or ("en",), default_content_locale=default or (tags or ("en",))[0]
    )
    client.app.state.sm_records.settings = settings
    return settings


def field(key: str, type_: str, *, indexed: bool = True, **options: Any) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": False,
        "unique": False,
        "indexed": indexed,
        "default": None,
        "help": None,
        "constraints": {},
        "options": options,
    }


async def make_type(client, *, translatable: bool = True, **cols: Any) -> dict:
    """``article`` — one text field, used as both title and slug source, so
    every record has a slug and the locale-scoped claim is exercised."""
    resp = await client.post(
        API,
        json={
            "key": TYPE_KEY,
            "label": "Article",
            "fields": [field("title", "text"), field("body", "text", indexed=False)],
            "display_field": "title",
            "slug_field": "title",
            "translatable": translatable,
            **cols,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_record(client, title: str, *, actor: str = ADMIN, **body: Any) -> dict:
    resp = await client.post(
        f"{API}/{TYPE_KEY}/records",
        json={"data": {"title": title, "body": "…"}, **body},
        headers=roles(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def translate(client, uuid: str, locale: str, *, actor: str = ADMIN, **body: Any):
    return await client.post(
        f"{API}/{TYPE_KEY}/records/{uuid}/translations",
        json={"locale": locale, **body},
        headers=roles(actor),
    )


async def publish(client, record: dict) -> dict:
    resp = await client.put(
        f"{API}/{TYPE_KEY}/records/{record['uuid']}",
        json={
            "expected_version": record["version"],
            "data": record["data"],
            "status": "published",
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def set_type(client, rtype: dict, **changes: Any):
    return await client.put(
        f"{API}/{TYPE_KEY}",
        json={"expected_version": rtype["version"], **changes},
        headers=roles(ADMIN),
    )
