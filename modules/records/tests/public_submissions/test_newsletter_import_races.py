"""``import_subscribers`` against a second transaction (newsletter PR 7, task 2).

Two real transactions need Postgres: in-memory SQLite shares one connection.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta

import pytest
from sm_records.contracts.newsletter_admin import lock_confirmation
from sm_records.contracts.newsletter_import import ImportRow
from sm_records.core import events
from sm_records.core.tenancy import tenant_scope
from sm_records.models import RecordType
from sm_records.records.services import records as record_service
from sqlalchemy import select

from tests.pg_support import USING_POSTGRES
from tests.support.newsletter_contract import TENANT, session, unbound
from tests.support.newsletter_import import KEY, SETTINGS, T, make_list, outcomes, run, seed, stored

pytestmark = pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")

ADA = "ada@example.org"


async def test_concurrent_signup_conflict_redecides(site):
    await make_list(site)
    async with session(site) as first:
        with tenant_scope(TENANT):
            rtype = (
                await first.execute(select(RecordType).where(RecordType.key == KEY))
            ).scalar_one()
            # What a signup of a new address writes (``subscribe._write``), held open.
            await record_service.create_record(
                first,
                rtype,
                data={},
                settings=SETTINGS,
                system={
                    "sm_email": ADA,
                    "sm_status": "pending",
                    "sm_consent_at": T,
                    "sm_locale": "en",
                    "sm_nonce": secrets.token_hex(16),
                },
            )
        task = asyncio.create_task(run(site, [ImportRow(email=ADA, status="confirmed")]))
        await asyncio.sleep(0.3)
        assert not task.done()
        await events.commit(first)
    assert outcomes(await asyncio.wait_for(task, 10)) == {ADA: "kept_pending"}
    assert (await stored(site, ADA)).data["sm_status"] == "pending"


@pytest.mark.parametrize(
    ("row", "outcome"),
    [
        (
            ImportRow(email=ADA, status="unsubscribed", unsubscribed_at=T + timedelta(1)),
            "unsubscribed",
        ),
        (ImportRow(email=ADA, status="confirmed", tags=["a"]), "updated"),
    ],
)
async def test_import_takes_the_row_lock(site, row, outcome):
    await make_list(site)
    await seed(site, ADA, confirmed_at=T)
    async with session(site) as first:
        with unbound():
            assert await lock_confirmation(first, tenant_id=TENANT, type_key=KEY, email=ADA)
        task = asyncio.create_task(run(site, [row]))
        await asyncio.sleep(0.3)
        assert not task.done()
        await first.commit()
    assert outcomes(await asyncio.wait_for(task, 10)) == {ADA: outcome}
