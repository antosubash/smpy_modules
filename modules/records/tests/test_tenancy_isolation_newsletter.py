"""The isolation matrix, part 6: a newsletter list (#101, design §4.4, §11).

``acme`` has a list, ``news``, with one pending subscriber and the two links
its confirmation carried; ``globex`` has no list of that key. On ``globex``'s
host ``acme``'s confirm link is the same ``410`` a forged one gets, its
unsubscribe link the same ``200`` that changes nothing, and the admin
unsubscribe is what a key nobody has gets. On the apex host — no tenant
resolved, where the mail's links point — the link binds ``acme`` itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_core.mail import install_mail_sender
from sm_records import boot, constants
from sm_records.public_submissions import mail_runner
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
from tests.newsletter_http import links_in, list_config, list_fields
from tests.submissions_http import Outbox, host_parts

pytestmark = pytest.mark.unbound_tenant

SUBMISSIONS = constants.PUBLIC_SUBMISSIONS_API_PREFIX.rstrip("/")
ORIGIN = {"Origin": "http://t", "Content-Type": "application/json"}
LIST = "news"


@pytest_asyncio.fixture
async def acme_list(tmp_path) -> AsyncIterator[tuple[AsyncClient, dict[str, str], str, object]]:
    """``(client, acme's link tokens, acme's subscriber uuid, db_state)``."""
    app, db_state = await build_app(tmp_path, tenancy="multi")
    host_parts(app)
    boot.mount_submission_views(app)
    getattr(app.state, constants.PACKAGE).settings = RecordsSettings(
        public_submissions_min_fill_seconds=0
    )
    outbox = Outbox()
    install_mail_sender(outbox)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            body = {
                "key": LIST,
                "label": "News",
                "fields": list_fields(),
                "public_submissions": list_config(),
            }
            assert (await client.post(API, json=body, headers=as_(ACME))).status_code == 201
            form = await client.get(f"{SUBMISSIONS}/{LIST}", headers=reader(ACME))
            sent = await client.post(
                f"{SUBMISSIONS}/{LIST}/submit",
                json={"data": {"sm_email": "ada@example.org"}, "token": form.json()["token"]},
                headers={**ORIGIN, **reader(ACME)},
            )
            assert sent.status_code == 202, sent.text
            await mail_runner.drain()
            tokens = {action: v["t"] for action, v in links_in(outbox.sent[0]).items()}
            listed = await client.get(f"{API}/{LIST}/records", headers=as_(ACME))
            (record,) = listed.json()["items"]
            yield client, tokens, record["uuid"], db_state
            await mail_runner.drain()
    finally:
        install_mail_sender(None)
        await db_state.engine.dispose()


async def _status(client: AsyncClient) -> str:
    listed = await client.get(f"{API}/{LIST}/records", headers=as_(ACME))
    return listed.json()["items"][0]["data"]["sm_status"]


@covers("POST /api/records/submissions/confirm")
async def test_acmes_confirm_link_is_nothing_on_globexs_host(acme_list):
    client, tokens, _, db_state = acme_list
    before = await tenant_rows(db_state)
    url = f"{SUBMISSIONS}/confirm"
    there = await client.post(url, json={"t": tokens["confirm"]}, headers=reader(GLOBEX))
    forged = await client.post(url, json={"t": "acme.news.x.1.AAAA.BBBB"}, headers=reader(GLOBEX))
    assert (there.status_code, there.json()) == (forged.status_code, forged.json())
    assert there.status_code == 410
    assert await tenant_rows(db_state) == before, "a globex request changed acme's rows"
    apex = await client.post(url, json={"t": tokens["confirm"]})
    assert apex.json() == {"status": "confirmed"}, "no tenant resolved: the link's tenant"
    assert await _status(client) == "confirmed"


@covers("POST /api/records/submissions/unsubscribe")
async def test_acmes_unsubscribe_link_changes_nothing_on_globexs_host(acme_list):
    client, tokens, _, db_state = acme_list
    before = await tenant_rows(db_state)
    url = f"{SUBMISSIONS}/unsubscribe"
    there = await client.post(url, json={"t": tokens["unsubscribe"]}, headers=reader(GLOBEX))
    assert (there.status_code, there.json()) == (200, {"status": "unsubscribed"})
    assert await tenant_rows(db_state) == before
    own = await client.post(url, json={"t": tokens["unsubscribe"]}, headers=reader(ACME))
    assert own.json() == {"status": "unsubscribed"}
    assert await _status(client) == "unsubscribed"


@covers("POST /api/records/types/{key}/records/{uuid}/submission/unsubscribe")
async def test_the_admin_unsubscribe_is_isolated(acme_list):
    client, _, uuid, db_state = acme_list
    before = await tenant_rows(db_state)
    await same_as_unknown(
        client,
        "POST",
        API + "/{key}/records/{uuid}/submission/unsubscribe",
        {"key": LIST, "uuid": uuid},
        {"key": NO_KEY, "uuid": NO_UUID},
        headers=as_(GLOBEX),
    )
    assert await tenant_rows(db_state) == before


@covers("GET /records/submissions/confirm", "GET /records/submissions/unsubscribe")
async def test_the_landing_pages_read_nothing_of_any_tenant(acme_list):
    """They verify nothing and query nothing: the same page on every host."""
    client, tokens, _, _ = acme_list
    inertia = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    for action in ("confirm", "unsubscribe"):
        url = f"/records/submissions/{action}?t={tokens[action]}"
        pages = [
            (await client.get(url, headers={**inertia, **extra})).json()["props"]
            for extra in ({}, reader(ACME), reader(GLOBEX))
        ]
        assert pages[0] == pages[1] == pages[2]
        assert pages[0]["token"] == tokens[action]
