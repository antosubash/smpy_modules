"""A newsletter list on the submissions harness, and what a subscriber does (#101).

Builds on :mod:`tests.submissions_http`: ``site`` is that harness, and
``newsletter`` adds a list that accepts signups plus the landing pages, which
a host mounts from ``on_startup``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest_asyncio
from httpx import AsyncClient
from sm_records import boot
from sm_records.public_submissions import mail_runner

from tests.app_harness import ADMIN, field, roles
from tests.public_submissions_support import create
from tests.submissions_http import JSON, SUBMISSIONS, load
from tests.submissions_http import records_of as _records_of

LIST = "news"
ADDRESS = "Reader@Example.org "
STORED = "reader@example.org"
_LINK = re.compile(r"https://site\.example/records/submissions/(confirm|unsubscribe)\?\S+")


def list_fields() -> list[dict[str, Any]]:
    """One optional ordinary field beside the system ones."""
    first = field("first_name", indexed=False)
    first["constraints"] = {"max_length": 100}
    return [first]


def list_config(**overrides: Any) -> dict[str, Any]:
    return {"kind": "subscription", "enabled": True, "public_fields": ["first_name"], **overrides}


async def newsletter_type(client: AsyncClient, key: str = LIST, **config: Any) -> dict:
    resp = await create(client, key, fields=list_fields(), config=list_config(**config))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest_asyncio.fixture
async def newsletter(site) -> AsyncIterator[AsyncClient]:
    """``site`` with a list keyed ``news`` and the landing pages mounted."""
    boot.mount_submission_views(site.app)
    await newsletter_type(site)
    yield site


async def signup(
    client: AsyncClient,
    address: Any = ADDRESS,
    key: str = LIST,
    *,
    data: dict[str, Any] | None = None,
    **body: Any,
):
    token = (await load(client, key))["token"]
    payload = {"data": {"sm_email": address, **(data or {})}, "token": token, **body}
    response = await client.post(f"{SUBMISSIONS}/{key}/submit", json=payload, headers=JSON)
    await mail_runner.drain()
    return response


def links_in(message: Any) -> dict[str, dict[str, str]]:
    """``{action: {"t": token, "l": locale}}`` from a confirmation's text."""
    out: dict[str, dict[str, str]] = {}
    for match in _LINK.finditer(message.text):
        query = parse_qs(urlsplit(match.group(0)).query)
        out[match.group(1)] = {name: values[0] for name, values in query.items()}
    return out


async def follow(
    client: AsyncClient, action: str, token: Any, *, form: bool = False, **headers: str
):
    """``POST`` a link's token, as the landing page (JSON) or a plain form would."""
    url = f"{SUBMISSIONS}/{action}"
    if form:
        return await client.post(url, data={"t": token}, headers=headers)
    return await client.post(url, json={"t": token}, headers=headers)


async def records_of(client: AsyncClient, key: str = LIST, **kw: Any) -> list:
    return await _records_of(client, key, **kw)


async def subscriber(client: AsyncClient, key: str = LIST, *, trashed: bool = False) -> dict:
    (record,) = await records_of(client, key, trashed=trashed)
    return record


async def admin(client: AsyncClient, uuid: str, action: str, key: str = LIST):
    return await client.post(
        f"/api/records/types/{key}/records/{uuid}/submission/{action}", headers=roles(ADMIN)
    )
