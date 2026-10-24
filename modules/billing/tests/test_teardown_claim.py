"""The teardown claim: one run at a time, outcomes only from the claim holder,
backoff on every pass, cleared by success (#92). Real separate sessions, so
this runs as-is on SQLite and on Postgres (``SM_TEST_DATABASE_URL``)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fake_provider import FakeProvider
from sm_billing import teardown_claim
from sm_billing.contracts.provider import ProviderError
from sm_billing.models import Customer
from sm_billing.reconcile import reconcile
from sm_billing.sweep import run_teardown
from teardown_helpers import _customer, _delete, _make_due, _paying_tenant
from tenants.models import Tenant


@pytest.fixture
def fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _silently_deleted(app, fake, **kw) -> str:
    """A paying tenant whose row is gone but whose event never ran."""
    tenant_id = await _paying_tenant(app, fake, **kw)
    async with app.state.sm.db.session_factory() as session:
        await session.delete(await session.get(Tenant, tenant_id))
        await session.commit()
    return tenant_id


def _slow(fake, method: str, seconds: float = 0.05) -> None:
    """Hold ``method`` open, so a second run gets to its claim mid-call."""
    original = getattr(fake, method)

    async def slow(*args, **kwargs):
        await asyncio.sleep(seconds)
        return await original(*args, **kwargs)

    setattr(fake, method, slow)


async def test_two_concurrent_runs_make_one_provider_pass_and_one_attempt(app, fake):
    tenant_id = await _silently_deleted(app, fake, with_sub=False)
    fake.fail.add("live_subscription_ids")
    _slow(fake, "expire_checkout")
    results = await asyncio.gather(
        run_teardown(app, tenant_id), run_teardown(app, tenant_id), return_exceptions=True
    )
    assert sorted(type(r).__name__ for r in results) == ["NoneType", "ProviderError"]
    assert len(fake.called("expire_checkout")) == 1
    assert len(fake.called("live_subscription_ids")) == 1
    assert (await _customer(app, tenant_id)).teardown_attempts == 1


async def test_two_concurrent_successes_cancel_once(app, fake):
    tenant_id = await _silently_deleted(app, fake)
    _slow(fake, "cancel_now")
    results = await asyncio.gather(run_teardown(app, tenant_id), run_teardown(app, tenant_id))
    assert results.count(None) == 1 and ["sub_1"] in results
    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]


async def test_only_one_of_many_concurrent_claims_wins(app, fake):
    tenant_id = await _silently_deleted(app, fake)
    tokens = await asyncio.gather(*(teardown_claim.claim(app, tenant_id) for _ in range(5)))
    assert sum(t is not None for t in tokens) == 1


async def test_a_crashed_claim_expires_after_the_lease(app, fake):
    tenant_id = await _silently_deleted(app, fake)
    assert await teardown_claim.claim(app, tenant_id) is not None  # its run dies here
    assert await run_teardown(app, tenant_id) is None  # held: no provider call
    assert fake.calls == []
    await _make_due(app, tenant_id)  # the lease ran out
    assert await run_teardown(app, tenant_id) == ["sub_1"]


async def test_a_run_that_lost_its_claim_writes_nothing(app, fake):
    tenant_id = await _silently_deleted(app, fake)
    stale = await teardown_claim.claim(app, tenant_id)
    await _make_due(app, tenant_id)  # lease over, another run claims
    current = await teardown_claim.claim(app, tenant_id)
    await teardown_claim.failed(app, tenant_id, stale)
    await teardown_claim.succeeded(app, tenant_id, stale)
    customer = await _customer(app, tenant_id)
    assert customer.teardown_attempts == 0
    assert customer.teardown_next_attempt_at.replace(tzinfo=UTC) == current


async def test_a_done_customer_with_a_wrong_key_backs_off(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    assert (await _customer(app, tenant_id)).teardown_done_at is not None
    fake.missing.add("fetch_subscription")  # the key now points elsewhere

    first = await reconcile(app)  # reconcile_one's recheck of the mirrored row
    assert [t for t, _ in first.errors] == [tenant_id]
    customer = await _customer(app, tenant_id)
    assert customer.teardown_attempts == 1
    assert customer.teardown_next_attempt_at.replace(tzinfo=UTC) > datetime.now(UTC)

    fake.calls.clear()
    second = await reconcile(app)
    assert (second.errors, fake.calls) == ([], [])


async def test_success_clears_the_backoff(app, fake):
    tenant_id = await _paying_tenant(app, fake)
    fake.fail.add("cancel_now")
    await _delete(app, tenant_id)
    customer = await _customer(app, tenant_id)
    assert (customer.teardown_attempts, customer.teardown_done_at) == (1, None)

    fake.fail.clear()
    await _make_due(app, tenant_id)
    await reconcile(app)
    customer = await _customer(app, tenant_id)
    assert customer.teardown_done_at is not None
    assert (customer.teardown_attempts, customer.teardown_next_attempt_at) == (0, None)


async def test_a_late_run_finishing_leaves_the_takeovers_backoff_alone(app, fake):
    """A stalls in checkout expiry past its lease; B takes over and fails; A then
    completes. A may stamp done, but B's attempt count and next due must stand."""
    tenant_id = await _silently_deleted(app, fake)
    original, stalled, resume = fake.expire_checkout, asyncio.Event(), asyncio.Event()

    async def expire_once_stalled(session_id: str) -> None:
        if not stalled.is_set():
            stalled.set()
            await resume.wait()
        await original(session_id)

    fake.expire_checkout = expire_once_stalled
    run_a = asyncio.create_task(run_teardown(app, tenant_id))
    await stalled.wait()
    await _make_due(app, tenant_id)  # A's lease lapses
    fake.fail.add("live_subscription_ids")
    with pytest.raises(ProviderError):
        await run_teardown(app, tenant_id)  # B claims, fails, books attempt 1
    b_due = (await _customer(app, tenant_id)).teardown_next_attempt_at
    fake.fail.clear()
    resume.set()
    await run_a
    customer = await _customer(app, tenant_id)
    assert customer.teardown_done_at is not None
    assert customer.teardown_attempts == 1
    assert customer.teardown_next_attempt_at == b_due


async def test_a_failure_after_done_keeps_done(app, fake):
    """The recheck failing never un-does a finished teardown."""
    tenant_id = await _paying_tenant(app, fake)
    await _delete(app, tenant_id)
    fake.fail.add("fetch_subscription")
    with pytest.raises(ProviderError):
        await run_teardown(app, tenant_id)
    async with app.state.sm.db.session_factory() as session:
        assert (await session.get(Customer, tenant_id)).teardown_done_at is not None
