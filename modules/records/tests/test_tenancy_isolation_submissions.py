"""The isolation matrix, part 5: website submissions (#101).

``acme`` has a contact-form type, ``contact``, that accepts submissions and
holds one; ``globex`` has no type of that key. Asked on ``globex``'s host,
``acme``'s form is exactly what a key nobody has is — for the definition, the
submit and the three admin actions — and no tenant at all is the shared 404.
The fixture checks on the way out that nothing ``acme`` owns changed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_records import constants
from sm_records.settings import RecordsSettings

from tests.app_harness import build_app
from tests.isolation_support import (
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
from tests.public_submissions_support import contact_fields, form_config
from tests.submissions_http import host_parts

pytestmark = pytest.mark.unbound_tenant

SUBMISSIONS = constants.PUBLIC_SUBMISSIONS_API_PREFIX.rstrip("/")
ORIGIN = {"Origin": "http://t", "Content-Type": "application/json"}
FORM = "contact"
DATA = {"name": "Ada", "email": "ada@example.org", "message": "Hello"}


async def _token(client: AsyncClient, tenant: str) -> str:
    resp = await client.get(f"{SUBMISSIONS}/{FORM}", headers=reader(tenant))
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest_asyncio.fixture
async def acme_form(tmp_path) -> AsyncIterator[tuple[AsyncClient, str, str]]:
    """``(client, acme's token, acme's submission uuid)``."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    host_parts(app)
    services = getattr(app.state, constants.PACKAGE)
    services.settings = RecordsSettings(public_submissions_min_fill_seconds=0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        body = {
            "key": FORM,
            "label": "Contact",
            "fields": contact_fields(),
            "public_submissions": form_config(enabled=True),
        }
        made = await client.post(API, json=body, headers=as_(ACME))
        assert made.status_code == 201, made.text
        token = await _token(client, ACME)
        sent = await client.post(
            f"{SUBMISSIONS}/{FORM}/submit",
            json={"data": DATA, "token": token},
            headers={**ORIGIN, **reader(ACME)},
        )
        assert sent.status_code == 202, sent.text
        listed = await client.get(f"{API}/{FORM}/records", headers=as_(ACME))
        (record,) = listed.json()["items"]
        before = await tenant_rows(db_state)
        yield client, token, record["uuid"]
        assert await tenant_rows(db_state) == before, "a globex request changed acme's rows"
    await db_state.engine.dispose()


@covers("GET /api/records/submissions/{type_key}")
async def test_acmes_form_is_unknown_on_globexs_host(acme_form):
    client, _, _ = acme_form
    await same_as_unknown(
        client,
        "GET",
        SUBMISSIONS + "/{key}",
        {"key": FORM},
        {"key": NO_KEY},
        headers=reader(GLOBEX),
    )
    missing = await client.get(f"{SUBMISSIONS}/{FORM}")
    assert missing.status_code == 404, "no tenant resolved is the shared 404"


@covers("POST /api/records/submissions/{type_key}/submit")
async def test_acmes_token_and_form_are_nothing_on_globexs_host(acme_form):
    client, token, _ = acme_form
    await same_as_unknown(
        client,
        "POST",
        SUBMISSIONS + "/{key}/submit",
        {"key": FORM},
        {"key": NO_KEY},
        headers={**ORIGIN, **reader(GLOBEX)},
        body=lambda _probes: {"data": DATA, "token": token},
        status=400,
    )
    anonymous = await client.post(
        f"{SUBMISSIONS}/{FORM}/submit", json={"data": DATA, "token": token}, headers=ORIGIN
    )
    assert anonymous.status_code == 404
    listed = await client.get(f"{API}/{FORM}/records", headers=as_(GLOBEX))
    assert listed.status_code == 404, "globex still has no such type"


@covers(
    "POST /api/records/types/{key}/records/{uuid}/submission/resend",
    "POST /api/records/types/{key}/records/{uuid}/submission/spam",
    "POST /api/records/types/{key}/records/{uuid}/submission/not-spam",
)
async def test_the_admin_actions_are_isolated(acme_form):
    client, _, uuid = acme_form
    for action in ("resend", "spam", "not-spam"):
        await same_as_unknown(
            client,
            "POST",
            API + "/{key}/records/{uuid}/submission/" + action,
            {"key": FORM, "uuid": uuid},
            {"key": NO_KEY, "uuid": NO_UUID},
            headers=as_(GLOBEX),
        )
