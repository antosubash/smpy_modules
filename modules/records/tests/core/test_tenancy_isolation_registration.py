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
from sm_records.core import boot, constants
from sm_records.core.settings import RecordsSettings
from sm_records.public_submissions import links

from tests.support.app_harness import build_app
from tests.support.isolation_support import (
    ACME,
    API,
    GLOBEX,
    NO_KEY,
    NO_UUID,
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
    """``(client, acme's event, acme's token)``; ``client.record`` is acme's one registration."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    host_parts(app)
    boot.mount_submission_views(app)
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
        sent = await client.post(
            f"{SUBMISSIONS}/{TYPE}/submit",
            json={"data": {"sm_email": "a@example.org", "sm_name": "Ada"}, "token": token},
            headers={**ORIGIN, **reader(ACME)},
        )
        assert sent.status_code == 202, sent.text
        listed = await client.get(f"{API}/{TYPE}/records", headers=as_(ACME))
        (client.record,) = listed.json()["items"]  # type: ignore[attr-defined]
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
    assert len(listed.json()["items"]) == 1 and event


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


@covers("POST /api/records/submissions/cancel")
async def test_acmes_cancel_link_is_nothing_on_globexs_host(acme_registration):
    client, _, _ = acme_registration
    record = client.record  # type: ignore[attr-defined]
    good = links.sign(
        "submissions-test-secret",
        links.CANCEL,
        tenant=ACME,
        type_key=TYPE,
        uuid=record["uuid"],
        nonce=record["data"]["sm_nonce"],
    )
    await same_as_unknown(
        client,
        "POST",
        SUBMISSIONS + "/cancel",
        {"which": "acme"},
        {"which": "nobody"},
        headers=reader(GLOBEX),
        body=lambda probes: {"t": good if probes["which"] == "acme" else "junk"},
        status=200,
    )  # the same "cancelled" page, and the fixture checks nothing of acme's changed


@covers("POST /api/records/types/{key}/records/{uuid}/submission/cancel")
async def test_the_admin_cancel_is_isolated(acme_registration):
    client, _, _ = acme_registration
    await same_as_unknown(
        client,
        "POST",
        API + "/{key}/records/{uuid}/submission/cancel",
        {"key": TYPE, "uuid": client.record["uuid"]},  # type: ignore[attr-defined]
        {"key": NO_KEY, "uuid": NO_UUID},
        headers=as_(GLOBEX),
    )


@covers("GET /records/submissions/cancel")
async def test_the_cancel_page_reads_nothing_of_any_tenant(acme_registration):
    """It verifies nothing and queries nothing: the same page on every host."""
    client, _, _ = acme_registration
    inertia = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    pages = [
        (
            await client.get("/records/submissions/cancel?t=abc", headers={**inertia, **extra})
        ).json()["props"]
        for extra in ({}, reader(ACME), reader(GLOBEX))
    ]
    assert pages[0] == pages[1] == pages[2] and pages[0]["token"] == "abc"
    assert pages[0]["action"] == "cancel" and pages[0]["copy"]["button"]
