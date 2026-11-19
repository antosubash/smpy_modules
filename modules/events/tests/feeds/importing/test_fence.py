"""The import's lease: the claim, and the one guard every later state write passes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.feeds.importing.fence import LeaseLost, claim, fenced
from sm_events.models import EventImport
from sqlalchemy import select

from tests.feeds.importing.staging_support import make_import, seed

TENANT = "default"


async def _claim(db, imp, owner="w1", now=None):
    return await claim(db, tenant_id=TENANT, import_id=imp.id, owner=owner, now=now or utcnow())


async def test_claim_moves_uploaded_to_parsing_and_queued_to_running(db):
    cal = (await seed(db))["P"]
    for before, after in (("uploaded", "parsing"), ("queued", "running")):
        imp = await make_import(db, cal, status=before)
        answer = await _claim(db, imp)
        assert (answer.kind, answer.status) == ("claimed", after)
        await db.refresh(imp)
        assert (imp.status, imp.lease_owner) == (after, "w1")
        assert imp.lease_until > utcnow()


async def test_busy_while_the_lease_is_live_and_claimable_after(db):
    cal = (await seed(db))["P"]
    imp = await make_import(db, cal, status="queued")
    now = utcnow()
    assert (await _claim(db, imp, "a", now)).kind == "claimed"
    assert (await _claim(db, imp, "b", now + timedelta(seconds=10))).kind == "busy"
    later = now + constants.IMPORT_LEASE + timedelta(seconds=1)
    taken = await _claim(db, imp, "b", later)
    assert (taken.kind, taken.status) == ("claimed", "running")  # resumes where it was


@pytest.mark.parametrize("status", ["staged", "done", "failed"])
async def test_gone_for_a_state_that_is_not_claimable(db, status):
    imp = await make_import(db, (await seed(db))["P"], status=status)
    assert (await _claim(db, imp)).kind == "gone"


async def test_gone_for_a_missing_import_and_another_tenant(db):
    imp = await make_import(db, (await seed(db))["P"], status="queued")
    missing = await claim(db, tenant_id=TENANT, import_id=99999, owner="w", now=utcnow())
    other = await claim(db, tenant_id="other", import_id=imp.id, owner="w", now=utcnow())
    assert (missing.kind, other.kind) == ("gone", "gone")


async def test_fenced_writes_only_for_the_owner(db):
    imp = await make_import(db, (await seed(db))["P"], status="uploaded")
    await _claim(db, imp, "mine")
    await fenced(db, tenant_id=TENANT, import_id=imp.id, owner="mine", values={"total": 7})
    row = (await db.execute(select(EventImport.total))).scalar_one()
    assert row == 7
    with pytest.raises(LeaseLost):
        await fenced(db, tenant_id=TENANT, import_id=imp.id, owner="theirs", values={"total": 8})
    with pytest.raises(LeaseLost):  # right owner, wrong tenant
        await fenced(db, tenant_id="other", import_id=imp.id, owner="mine", values={"total": 9})


async def test_lease_lost_when_the_state_moved_on(db):
    imp = await make_import(db, (await seed(db))["P"], status="queued")
    await _claim(db, imp, "mine")
    await fenced(db, tenant_id=TENANT, import_id=imp.id, owner="mine", values={"status": "done"})
    with pytest.raises(LeaseLost):  # no longer parsing or running
        await fenced(db, tenant_id=TENANT, import_id=imp.id, owner="mine", values={"total": 1})
