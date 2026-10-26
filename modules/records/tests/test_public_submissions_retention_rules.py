"""The retention sweep's finer rules (#101): eligibility is re-checked under
the deletion lock, a pending window opens when a subscriber enters pending
and is not extended by resends, only finished delivery attempts are pruned,
and a sweep that loses its lease stops."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_records.models import tables_for
from sm_records.public_submissions import retention
from sm_records.services import types as type_service
from sqlalchemy import select, update

from tests.retention_support import (
    NOW,
    claim,
    claims,
    form,
    newsletter,
    record,
    subscriber,
    sweep,
    temp_db,
    uuids,
)
from tests.tenancy_support import session_in

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def db(tmp_path):
    async with temp_db(tmp_path) as state:
        yield state


async def test_a_subscriber_who_confirms_after_being_listed_is_kept(db, monkeypatch):
    """The candidates are read before the lock; a confirm landing in between
    must not be purged."""
    await newsletter(db)
    racing = await record(db, "news", age_days=40, **subscriber("pending"))
    original = retention._purge_one

    async def confirm_first(session, rtype, uuid, run):
        if uuid == racing:
            async with session_in(db, "default") as other:
                cls = tables_for(await type_service.get_type(other, "news")).record
                current = await other.get(cls, (await _id(other, cls, uuid)))
                await other.execute(
                    update(cls)
                    .where(cls.id == current.id, cls.tenant_id == "default")
                    .values(data={**current.data, "sm_status": "confirmed"})
                )
        return await original(session, rtype, uuid, run)

    monkeypatch.setattr(retention, "_purge_one", confirm_first)
    swept = await sweep(db)
    assert swept.purged == 0
    assert racing in await uuids(db, "news")


async def _id(session, cls, uuid):
    return (await session.execute(select(cls.id).where(cls.uuid == uuid))).scalar_one()


async def test_the_pending_window_opens_on_entering_pending_and_resends_do_not_extend_it(db):
    await newsletter(db)
    days = 30
    # Signed up 40 days ago and re-sent a confirmation yesterday: still due.
    resent = await record(
        db,
        "news",
        age_days=40,
        updated_days=1,
        **subscriber("pending"),
        sm_consent_at=(NOW - timedelta(days=40)).isoformat(),
    )
    # An old address that came back (unsubscribed → pending) five days ago.
    returned = await record(
        db,
        "news",
        age_days=400,
        **subscriber("pending"),
        sm_consent_at=(NOW - timedelta(days=5)).isoformat(),
    )
    swept = await sweep(db)
    assert swept.purged == 1, f"window is {days} days"
    assert await uuids(db, "news") == {returned}
    assert resent not in await uuids(db, "news")


async def test_only_finished_delivery_attempts_are_pruned(db):
    await form(db, retention_days=0)
    old = NOW - timedelta(days=31)
    # A sent, B failed (claim given back): the attempt can still resume, so
    # A's "sent" must survive however old it is, or the retry mails A again.
    retrying = await record(db, "contact", age_days=0)
    await claim(db, retrying, attempt="x", sent=old, who="a@x.org")
    await claim(db, retrying, attempt="x", who="b@x.org")
    # Everyone sent long ago and the record is marked notified: finished.
    done = await record(db, "contact", age_days=0, sm_notified_at=NOW.isoformat())
    await claim(db, done, attempt="y", sent=old, who="a@x.org")
    await claim(db, done, attempt="y", sent=old, who="b@x.org")
    # Finished but recent: kept until the horizon.
    recent = await record(db, "contact", age_days=0, sm_notified_at=NOW.isoformat())
    await claim(db, recent, attempt="z", sent=NOW, who="a@x.org")
    # All rows sent, but the record was never marked: not known finished.
    unmarked = await record(db, "contact", age_days=0)
    await claim(db, unmarked, attempt="w", sent=old, who="a@x.org")
    # The record is gone: nothing can resume, whatever the rows say.
    await claim(db, "e" * 32, attempt="v", who="c@x.org")
    await claim(db, "f" * 32, tenant="acme", sent=old, who="acme@x.org")

    swept = await sweep(db)

    assert swept.deliveries == 3
    assert await claims(db) == sorted(
        [
            (retrying, "a@x.org"),
            (retrying, "b@x.org"),
            (recent, "a@x.org"),
            (unmarked, "a@x.org"),
        ]
    )
    # Another tenant's rows are never touched from this one's sweep.
    assert await claims(db, "acme") == [("f" * 32, "acme@x.org")]


class _LostLease:
    async def acquire(self) -> bool:
        return True

    async def refresh(self) -> bool:
        return False

    async def release(self) -> bool:
        return False


async def test_a_sweep_that_loses_its_lease_stops_and_keeps_its_batch(db, monkeypatch):
    await form(db, retention_days=1)
    for _ in range(3):
        await record(db, "contact", age_days=5)
    monkeypatch.setattr(retention, "lease", lambda *a, **k: _LostLease())
    monkeypatch.setattr(retention, "REFRESH_EVERY", 0)
    swept = await sweep(db)
    assert swept is not None and swept.purged == 0 and swept.tenants == []
    assert len(await uuids(db, "contact")) == 3, "nothing deleted once ownership was lost"
