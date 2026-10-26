"""Pruning delivery bookkeeping (#101): only attempts recorded complete, newsletter
confirmations that can never resume, and attempts of records verifiably gone
— looked up at prune time, wherever they live — and never while the sweep's
lease is lost. "Finished" is never inferred from the rows that exist."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_records.public_submissions import retention
from sm_records.public_submissions.attempts import COMPLETE
from sm_records.public_submissions.retention_deliveries import prune_deliveries
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.tenancy import tenant_scope

from tests.retention_support import (
    NOW,
    S,
    claim,
    claims,
    form,
    newsletter,
    record,
    subscriber,
    sweep,
    temp_db,
)
from tests.tenancy_support import session_in

pytestmark = pytest.mark.unbound_tenant
OLD = NOW - timedelta(days=31)


@pytest.fixture
async def db(tmp_path):
    async with temp_db(tmp_path) as state:
        yield state


async def test_only_attempts_recorded_complete_are_pruned(db):
    await form(db, retention_days=0)
    # A sent, B failed (claim given back): resumable, kept however old.
    retrying = await record(db, "contact", age_days=0)
    await claim(db, retrying, attempt="x", sent=OLD, who="a@x.org")
    await claim(db, retrying, attempt="x", who="b@x.org")
    # A resend mailed A, then crashed before claiming B: every existing row is
    # sent and the record is marked from an earlier attempt -- still not
    # complete, so A's marker must survive or the recovery mails A again.
    crashed = await record(db, "contact", age_days=0, sm_notified_at=NOW.isoformat())
    await claim(db, crashed, attempt="y", sent=OLD, who="a@x.org")
    # Recorded complete and past the horizon: pruned, completion row included.
    done = await record(db, "contact", age_days=0, sm_notified_at=NOW.isoformat())
    await claim(db, done, attempt="z", sent=OLD, who="a@x.org")
    await claim(db, done, attempt="z", sent=OLD, who=COMPLETE)
    # Complete but recent: kept until the horizon.
    recent = await record(db, "contact", age_days=0)
    await claim(db, recent, attempt="r", sent=NOW, who="a@x.org")
    await claim(db, recent, attempt="r", sent=NOW, who=COMPLETE)
    # The record is gone: nothing can resume, whatever the rows say.
    await claim(db, "e" * 32, attempt="v", who="c@x.org")
    await claim(db, "f" * 32, tenant="acme", sent=OLD, who="acme@x.org")

    swept = await sweep(db)

    assert swept.deliveries == 3
    assert await claims(db) == sorted(
        [
            (retrying, "a@x.org"),
            (retrying, "b@x.org"),
            (crashed, "a@x.org"),
            (recent, "a@x.org"),
            (recent, COMPLETE),
        ]
    )
    assert await claims(db, "acme") == [("f" * 32, "acme@x.org")], "another tenant's rows"


async def test_a_live_record_outside_any_submission_type_is_not_gone(db):
    """The lookup is the record's own, at prune time — not an inventory of
    submission types taken earlier, which a record of a type created since
    (or one that moved collections) would be missing from."""
    async with session_in(db, "default") as session:
        plain = await type_service.create_type(
            session,
            key="plain",
            label="Plain",
            settings=S,
            fields_raw=[{"key": "name", "type": "text", "label": "Name"}],
        )
        assert plain.public_submissions is None
        live = (
            await record_service.create_record(session, plain, data={"name": "x"}, settings=S)
        ).uuid
    await form(db)  # a submission type, so the tenant is swept
    await claim(db, live, attempt="p", sent=OLD, who="a@x.org")
    await claim(db, live, attempt="p", who="b@x.org")
    assert (await sweep(db)).deliveries == 0
    assert len(await claims(db)) == 2


async def test_a_confirmation_that_can_never_resume_is_retired(db):
    await newsletter(db)
    confirmed = await record(db, "news", age_days=0, **subscriber("confirmed"))
    await claim(db, confirmed, attempt="c", who="hash-1")
    waiting = await record(db, "news", age_days=0, **subscriber("pending"))
    await claim(db, waiting, attempt="w", claimed=OLD, who="hash-2")
    swept = await sweep(db)
    assert swept.deliveries == 1
    assert await claims(db) == [(waiting, "hash-2")], "a pending one can still be resent"


async def test_pruning_stops_when_the_lease_is_lost(db):
    await form(db)
    await claim(db, "e" * 32, attempt="v", sent=OLD, who="c@x.org")

    async def lost() -> None:
        raise retention.LeaseLost(retention.LEASE_NAME)

    with tenant_scope("default"), pytest.raises(retention.LeaseLost):
        await prune_deliveries(db.session_factory, NOW - timedelta(days=30), lost)
    assert len(await claims(db)) == 1, "nothing deleted without the lease"
