"""Concurrent duplicates of one ``Idempotency-Key`` run the handler at most once.

The suite's default in-memory database shares one connection between every
session, so concurrent requests interleave inside one transaction and cannot
model this. Here the app runs on a **file** SQLite database (its own pooled
connections, WAL, ``busy_timeout``), or on Postgres under
``SM_TEST_DATABASE_URL``.
"""

from __future__ import annotations

import asyncio

import pytest
from quota_helpers import PREFIX
from simple_module_test.database import database_is_postgres
from usage_helpers import events


@pytest.fixture
def settings(settings, tmp_path):
    if database_is_postgres():
        return settings
    return settings.model_copy(
        update={"database_url": f"sqlite+aiosqlite:///{tmp_path / 'quota.db'}"}
    )


async def test_concurrent_duplicates_run_the_handler_at_most_once(quota_app, owner, runs):
    for round_ in range(2):  # the owner's plan allows 2
        headers = {"Idempotency-Key": f"dup-{round_}"}
        responses = await asyncio.gather(
            *(owner.get(f"{PREFIX}/count", headers=headers) for _ in range(4))
        )
        codes = [r.status_code for r in responses]
        # One runs; every duplicate is refused before the handler.
        assert sorted(codes) == [200, 409, 409, 409], [r.text for r in responses]
        assert {r.json()["detail"] for r in responses if r.status_code == 409} == {
            "idempotency_replay"
        }
    assert len(runs) == 2


async def test_a_failed_write_through_the_request_session_is_refunded(quota_app, owner):
    """The handler flushes a write on the request session and raises: on SQLite
    that session holds the write lock, which the refund must not wait behind."""
    from sm_billing.models import Plan, UsagePeriod
    from sqlalchemy import func, select

    factory = quota_app.state.sm.db.session_factory

    async def counter() -> int:
        async with factory() as session:
            stmt = select(func.coalesce(func.sum(UsagePeriod.used), 0)).where(
                UsagePeriod.tenant_id == owner.tenant_id
            )
            return int((await session.execute(stmt)).scalar_one())

    assert (await owner.get(f"{PREFIX}/count")).status_code == 200
    before = await counter()
    response = await owner.get(f"{PREFIX}/write-boom")
    assert response.status_code == 418
    assert await events(factory, owner.tenant_id, kind="refund") == 1
    assert await counter() == before  # the failed call is not charged
    async with factory() as session:  # and its write was rolled back
        stmt = select(func.count()).select_from(Plan).where(Plan.key.like("w-%"))
        assert (await session.execute(stmt)).scalar_one() == 0
