"""The suppression listing and the lookup by address (PR 6, Task 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_newsletter.core.suppression import email_hash
from sm_newsletter.subscribers.suppressions import (
    FINGERPRINT_LEN,
    list_suppressions,
    rows_for_email,
    visible_lists,
)

from tests.support.lift_world import seed_row
from tests.support.records_seed import restrict_list, seed_list

pytestmark = pytest.mark.unbound_tenant

T = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
ADA, BOB, CY = "ada@example.org", "bob@example.org", "cy@example.org"
ZERO = {"hard_bounce": 0, "complaint": 0, "imported_cleaned": 0, "unsubscribed": 0}


async def _list(db_state, tenant="default", roles=None, reason=None, offset=0, limit=50):
    async with db_state.session_factory() as s:
        return await list_suppressions(
            s, tenant_id=tenant, roles=roles, reason=reason, offset=offset, limit=limit
        )


async def _seed_three(db_state):
    await seed_list(db_state, "default")
    await seed_row(db_state, "default", ADA, "hard_bounce", at=T)
    await seed_row(db_state, "default", BOB, "complaint", at=T + timedelta(hours=1))
    await seed_row(db_state, "default", CY, "unsubscribed", key="news", at=T + timedelta(hours=2))


async def test_list_newest_first_with_counts(db_state):
    await _seed_three(db_state)
    items, total, counts = await _list(db_state)
    assert [r.email_hash for r in items] == [email_hash(CY), email_hash(BOB), email_hash(ADA)]
    assert total == 3
    assert counts == {**ZERO, "hard_bounce": 1, "complaint": 1, "unsubscribed": 1}
    assert items[0].version == items[0].created_at.isoformat()
    assert FINGERPRINT_LEN == 12
    page, total, _ = await _list(db_state, offset=1, limit=1)
    assert [r.email_hash for r in page] == [email_hash(BOB)] and total == 3


async def test_filter_by_reason(db_state):
    await _seed_three(db_state)
    items, total, counts = await _list(db_state, reason="complaint")
    assert [r.reason for r in items] == ["complaint"] and total == 1
    assert counts["hard_bounce"] == 1  # counts ignore the reason filter


async def test_restricted_list_rows_hidden(db_state):
    await _seed_three(db_state)
    await restrict_list(db_state, "default", "news", ["editor"])
    async with db_state.session_factory() as s:
        assert await visible_lists(s, tenant_id="default", roles=["viewer"]) == []
    items, total, counts = await _list(db_state, roles=["viewer"])
    assert {r.reason for r in items} == {"hard_bounce", "complaint"} and total == 2
    assert counts["unsubscribed"] == 0
    async with db_state.session_factory() as s:
        assert await rows_for_email(s, tenant_id="default", roles=["viewer"], email=CY) == []
        seen = await rows_for_email(s, tenant_id="default", roles=["editor"], email=CY)
    assert [r.reason for r in seen] == ["unsubscribed"]
    _, total, _ = await _list(db_state, roles=["editor"])
    assert total == 3


async def test_rows_for_email_spelling_insensitive(db_state):
    await _seed_three(db_state)
    await seed_row(db_state, "default", ADA, "complaint", at=T + timedelta(hours=3))
    async with db_state.session_factory() as s:
        found = await rows_for_email(s, tenant_id="default", roles=None, email="  ADA@Example.ORG")
    assert [r.reason for r in found] == ["complaint", "hard_bounce"]
    assert {r.email_hash for r in found} == {email_hash(ADA)}


async def test_list_pins_the_tenant(db_state):
    await _seed_three(db_state)
    await seed_row(db_state, "b", ADA, "hard_bounce", at=T)
    items, total, counts = await _list(db_state, tenant="b")
    assert total == 1 and counts == {**ZERO, "hard_bounce": 1}
    assert [r.reason for r in items] == ["hard_bounce"]
    async with db_state.session_factory() as s:
        found = await rows_for_email(s, tenant_id="b", roles=None, email=BOB)
    assert found == []
