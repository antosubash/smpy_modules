"""Lifting a suppression: the checks in order, the audit row (PR 6, Task 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from simple_module_db.listeners import current_user_id
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import (
    InvalidQuery,
    LiftEmailMismatch,
    LiftNotAllowed,
    OptOutStands,
    SuppressionChanged,
)
from sm_newsletter.core.suppression import email_hash, suppressed
from sm_newsletter.core.suppression.reconcile import reconcile_async
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.subscribers.lift import NOTE_MAX, lift, list_lifts
from sm_newsletter.subscribers.suppressions import rows_for_email

from tests.support.lift_world import lifts, purge, rows, seed_row
from tests.support.records_seed import restrict_list, seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

ADA = "ada@example.org"
NOW = datetime.now(UTC)


async def _row(db_state, email=ADA, tenant="default"):
    async with db_state.session_factory() as s:
        found = await rows_for_email(s, tenant_id=tenant, roles=None, email=email)
    assert len(found) == 1
    return found[0]


async def _lift(
    db_state, row, *, email=ADA, note="asked us by phone", version=None, sid=None, roles=None
):
    with tenant_scope("default"):
        async with db_state.session_factory() as s:
            token = current_user_id.set("admin-1")
            try:
                out = await lift(
                    s,
                    tenant_id="default",
                    roles=roles,
                    suppression_id=row.id if sid is None else sid,
                    version=row.version if version is None else version,
                    email=email,
                    note=note,
                    now=NOW,
                )
                await finalize_session(s)
                return out
            finally:
                current_user_id.reset(token)


async def test_lift_hard_bounce_writes_audit(db_state):
    await seed_row(db_state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=1))
    row = await _row(db_state)
    out = await _lift(db_state, row, email=" ADA@example.org ", note="  mailbox fixed  ")
    assert await rows(db_state) == []
    [audit] = await lifts(db_state)
    assert audit.id == out.id
    assert (audit.email_hash, audit.reason, audit.list_type_key) == (
        email_hash(ADA),
        "hard_bounce",
        "",
    )
    assert audit.suppressed_at == row.created_at and audit.lifted_at == NOW
    assert (audit.lifted_by, audit.note, audit.source) == ("admin-1", "mailbox fixed", "send")
    async with db_state.session_factory() as s:
        assert await suppressed(s, tenant_id="default", emails=[ADA]) == set()
        page, total = await list_lifts(s, tenant_id="default", roles=None, offset=0, limit=10)
    assert total == 1 and page[0].id == out.id


async def test_lift_imported_cleaned(db_state):
    await seed_row(db_state, "default", ADA, "imported_cleaned", at=NOW - timedelta(days=1))
    await _lift(db_state, await _row(db_state))
    assert await rows(db_state) == [] and len(await lifts(db_state)) == 1


async def test_complaint_never_lifts(db_state):
    await seed_row(db_state, "default", ADA, "complaint", at=NOW - timedelta(days=1))
    with pytest.raises(LiftNotAllowed):
        await _lift(db_state, await _row(db_state))
    assert len(await rows(db_state)) == 1 and await lifts(db_state) == []


async def test_wrong_email_is_mismatch_even_for_complaint(db_state):
    await seed_row(db_state, "default", ADA, "complaint", at=NOW - timedelta(days=1))
    with pytest.raises(LiftEmailMismatch):
        await _lift(db_state, await _row(db_state), email="bob@example.org")
    with pytest.raises(LiftEmailMismatch):
        await _lift(db_state, await _row(db_state), email="   ")


async def _unsubscribed_row(db_state, at):
    await seed_list(db_state, "default")
    await seed_row(db_state, "default", ADA, "unsubscribed", key="news", at=at)
    return await _row(db_state)


async def test_lift_unsubscribed_requires_later_confirmation(db_state):
    row = await _unsubscribed_row(db_state, NOW - timedelta(hours=1))
    uuid = await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    with pytest.raises(OptOutStands):  # (a) still unsubscribed
        await _lift(db_state, row)
    await purge(db_state, "default", uuid)
    await seed_subscriber(db_state, "default", ADA, "confirmed")  # confirmed now: later
    await _lift(db_state, row)  # (b)
    assert await rows(db_state) == [] and len(await lifts(db_state)) == 1


async def test_lift_unsubscribed_confirmed_before_the_row_stands(db_state):
    row = await _unsubscribed_row(db_state, NOW + timedelta(hours=1))
    await seed_subscriber(db_state, "default", ADA, "confirmed")  # (c) earlier than the row
    with pytest.raises(OptOutStands):
        await _lift(db_state, row)
    assert len(await rows(db_state)) == 1


async def test_lift_after_refresh_is_409(db_state):
    await seed_row(db_state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=2))
    old = await _row(db_state)
    await seed_row(db_state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=1))
    with pytest.raises(SuppressionChanged):
        await _lift(db_state, old)
    assert len(await rows(db_state)) == 1 and await lifts(db_state) == []


async def test_lift_other_tenants_id_is_404(db_state):
    await seed_row(db_state, "b", ADA, "hard_bounce", at=NOW - timedelta(days=1))
    theirs = await _row(db_state, tenant="b")
    with pytest.raises(NotFound):
        await _lift(db_state, theirs)
    assert len(await rows(db_state, "b")) == 1 and await lifts(db_state, "b") == []


@pytest.mark.parametrize(
    ("note", "version"),
    [
        ("", None),
        ("   ", None),
        ("x" * (NOTE_MAX + 1), None),
        ("bad\x00note", None),
        ("tab\tnote", None),
        ("fine", "not-a-date"),
        ("fine", "2026-11-03T12:00:00"),  # naive
    ],
)
async def test_note_required_and_bounded(db_state, note, version):
    await seed_row(db_state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=1))
    row = await _row(db_state)
    with pytest.raises(InvalidQuery) as err:
        await _lift(db_state, row, note=note, version=version)
    assert err.value.detail.split(":")[0] == ("note" if version is None else "version")
    assert len(await rows(db_state)) == 1


async def test_multiline_note_of_max_length_lifts(db_state):
    await seed_row(db_state, "default", ADA, "hard_bounce", at=NOW - timedelta(days=1))
    note = "a\n" + "b" * (NOTE_MAX - 2)
    out = await _lift(db_state, await _row(db_state), note=note)
    assert out.note == note


async def test_reconcile_does_not_resurrect_lifted_unsubscribe(db_state):
    row = await _unsubscribed_row(db_state, NOW - timedelta(hours=1))
    uuid = await seed_subscriber(db_state, "default", ADA, "unsubscribed")
    await purge(db_state, "default", uuid)
    await seed_subscriber(db_state, "default", ADA, "confirmed")
    await _lift(db_state, row)
    result = await reconcile_async(db_state.session_factory, now=NOW)
    assert result["suppressed"] == 0 and await rows(db_state) == []


async def test_restricted_list_lift_is_404(db_state):
    """Focus 5: a write on a row of a list the caller cannot read is a 404."""
    row = await _unsubscribed_row(db_state, NOW - timedelta(hours=1))
    await seed_subscriber(db_state, "default", ADA, "confirmed")  # liftable for a reader
    await restrict_list(db_state, "default", "news", ["editor"])
    with pytest.raises(NotFound):
        await _lift(db_state, row, roles=["viewer"])
    assert len(await rows(db_state)) == 1 and await lifts(db_state) == []
    await _lift(db_state, row, roles=["editor"])
    assert await rows(db_state) == []


async def test_restricted_list_lifts_hidden(db_state):
    """Focus 5: a lift on a list the caller cannot read is absent from the log
    and its total; a tenant-wide lift stays visible."""
    row = await _unsubscribed_row(db_state, NOW - timedelta(hours=1))
    await seed_subscriber(db_state, "default", ADA, "confirmed")
    await _lift(db_state, row)
    await seed_row(db_state, "default", "bo@example.org", "hard_bounce", at=NOW)
    await _lift(db_state, await _row(db_state, email="bo@example.org"), email="bo@example.org")
    await restrict_list(db_state, "default", "news", ["editor"])

    async def log(roles):
        async with db_state.session_factory() as s:
            page, total = await list_lifts(s, tenant_id="default", roles=roles, offset=0, limit=10)
        return sorted(r.reason for r in page), total

    assert await log(["viewer"]) == (["hard_bounce"], 1)
    assert await log(["editor"]) == (["hard_bounce", "unsubscribed"], 2)
