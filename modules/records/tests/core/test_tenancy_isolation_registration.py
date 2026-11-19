"""The isolation matrix, part 6: event registration (PR 9).

``acme`` has a registration type that accepts registrations and a published event with seats;
``globex`` has neither. Asked on ``globex``'s host, ``acme``'s registration form, its availability
and its token are exactly what a key nobody has is, and nothing ``acme`` owns (records, seats,
counters) changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_records.core import constants
from sm_records.core.settings import RecordsSettings

from tests.support.app_harness import build_app
from tests.support.isolation_support import (
    ACME,
    API,
    GLOBEX,
    NO_KEY,
    as_,
    covers,
    reader,
    same_as_unknown,
    tenant_rows,
)
from tests.support.public_submissions_support import create
from tests.support.registration_http import TYPE, reg_config, reg_fields, seed_event
from tests.support.submissions_http import host_parts

pytestmark = pytest.mark.unbound_tenant

SUBMISSIONS = constants.PUBLIC_SUBMISSIONS_API_PREFIX.rstrip("/")
ORIGIN = {"Origin": "http://t", "Content-Type": "application/json"}


@pytest_asyncio.fixture
async def acme_registration(tmp_path) -> AsyncIterator[tuple[AsyncClient, dict, str]]:
    """``(client, acme's event, acme's token)``."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    host_parts(app)
    getattr(app.state, constants.PACKAGE).settings = RecordsSettings(
        public_submissions_min_fill_seconds=0
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.headers.update(as_(ACME))
        made = await create(client, TYPE, fields=reg_fields(), config=reg_config())
        assert made.status_code == 201, made.text
        client.headers.clear()
        event = await seed_event(db_state, tenant=ACME)
        loaded = await client.get(
            f"{SUBMISSIONS}/{TYPE}/registration",
            params={"event": event["event_id"], "occurrence": event["key"]},
            headers=reader(ACME),
        )
        assert loaded.status_code == 200, loaded.text
        token = loaded.json()["definition"]["token"]
        before = await tenant_rows(db_state)
        yield client, event, token
        assert await tenant_rows(db_state) == before, "a globex request changed acme's rows"
    await db_state.engine.dispose()


@covers("GET /api/records/submissions/{type_key}/registration")
async def test_acmes_registration_is_unknown_on_globexs_host(acme_registration):
    client, event, _ = acme_registration
    template = SUBMISSIONS + "/{key}/registration?event={event}&occurrence={occurrence}"
    probes = {"event": event["event_id"], "occurrence": event["key"]}
    await same_as_unknown(
        client,
        "GET",
        template,
        {"key": TYPE, **probes},
        {"key": NO_KEY, **probes},
        headers=reader(GLOBEX),
    )
    anonymous = await client.get(f"{SUBMISSIONS}/{TYPE}/registration", params=probes)
    assert anonymous.status_code == 404, "no tenant resolved is the shared 404"


async def test_acmes_registration_token_is_nothing_on_globexs_host(acme_registration):
    client, event, token = acme_registration
    await create_globex_type(client)
    sent = await client.post(
        f"{SUBMISSIONS}/{TYPE}/submit",
        json={"data": {"sm_email": "a@example.org", "sm_name": "A"}, "token": token},
        headers={**ORIGIN, **reader(GLOBEX)},
    )
    assert (sent.status_code, sent.json()["code"]) == (400, "form_expired")
    listed = await client.get(f"{API}/{TYPE}/records", headers=as_(ACME))
    assert listed.json()["items"] == [] and event


async def create_globex_type(client: AsyncClient) -> None:
    made = await client.post(
        API,
        json={
            "key": TYPE,
            "label": "Regs",
            "fields": reg_fields(),
            "public_submissions": reg_config(),
        },
        headers=as_(GLOBEX),
    )
    assert made.status_code == 201, made.text
