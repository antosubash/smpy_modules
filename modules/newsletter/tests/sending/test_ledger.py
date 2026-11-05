"""The SMTP attempt ledger and the rolling budget it feeds, on SQLite and Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.errors import SendBudgetExhausted
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import SendAttempt
from sm_newsletter.sending import budget, ledger
from sm_newsletter.sending.transport import DeliveryResult
from sqlalchemy import select

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


async def _attempt(state, tenant: str, *, at: datetime, outcome: str | None = None) -> None:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            row = await ledger.open_attempt(
                db,
                tenant_id=tenant,
                campaign_id=None,
                send_id=None,
                kind="test",
                recipient="a@example.org",
                now=at,
            )
            await finalize_session(db)
            if outcome is not None:
                await ledger.close_attempt(db, row, DeliveryResult(outcome, None, "x"))  # type: ignore[arg-type]
                await finalize_session(db)


@pytest.mark.unbound_tenant
async def test_counts_every_tenant(db_state):
    await _attempt(db_state, "a", at=NOW)
    await _attempt(db_state, "b", at=NOW)
    with tenant_scope("a"):
        assert await ledger.attempts_since(db_state.session_factory, since=NOW) == 2


async def test_rejected_not_counted(db_state):
    for outcome in ("accepted", "unknown", None, "rejected", "failed"):
        await _attempt(db_state, "default", at=NOW, outcome=outcome)
    assert await ledger.attempts_since(db_state.session_factory, since=NOW) == 3


async def test_window_edges(db_state):
    await _attempt(db_state, "default", at=NOW - timedelta(hours=24, seconds=1))
    await _attempt(db_state, "default", at=NOW - timedelta(hours=24))
    await _attempt(db_state, "default", at=NOW - timedelta(seconds=61))
    await _attempt(db_state, "default", at=NOW - timedelta(seconds=60))
    got = await budget.current_budget(db_state.session_factory, NewsletterSettings(), now=NOW)
    assert (got.day_used, got.minute_used) == (3, 1)


async def test_close_attempt_records_result(db_state, db):
    row = await ledger.open_attempt(
        db,
        tenant_id="default",
        campaign_id=None,
        send_id=None,
        kind="test",
        recipient="a@example.org",
        now=NOW,
    )
    await finalize_session(db)
    assert row.outcome == "pending"
    await ledger.close_attempt(db, row, DeliveryResult("rejected", 550, "5.1.1 No such user"))
    await finalize_session(db)
    async with db_state.session_factory() as other:
        stored = (await other.execute(select(SendAttempt))).scalars().one()
    assert (stored.outcome, stored.smtp_code, stored.detail) == (
        "rejected",
        550,
        "5.1.1 No such user",
    )
    assert (stored.kind, stored.tenant_id, stored.attempted_at) == ("test", "default", NOW)


async def test_admit_is_all_or_nothing(db_state):
    settings = NewsletterSettings(daily_limit=5, per_minute_limit=100)
    for _ in range(3):
        await _attempt(db_state, "default", at=NOW - timedelta(hours=1))
    got = await budget.admit(db_state.session_factory, settings, n=2, now=NOW)
    assert got.left == 2
    with pytest.raises(SendBudgetExhausted):
        await budget.admit(db_state.session_factory, settings, n=3, now=NOW)


def test_budget_left_is_the_tighter_window():
    got = budget.Budget(day_used=10, minute_used=29, daily_limit=100, per_minute_limit=30)
    assert (got.left, got.fits(1), got.fits(2)) == (1, True, False)
    over = budget.Budget(day_used=101, minute_used=0, daily_limit=100, per_minute_limit=30)
    assert (over.left, over.fits(0)) == (0, False)
