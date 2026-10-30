"""``consume_requests``: ``ai.requests`` metered where there is no request.

A Celery worker (images' ``classify`` and prompt steps) never builds the app,
so ``RequiresAiRequest`` cannot reach it. ``consume_requests`` charges the
meter through billing's ``usage_meter`` in its own short transaction - on the
caller's session factory, or, in a bare worker, on an engine of its own over
the host's database URL - and is unmetered (``True``) only when billing is
not installed at all: an installed billing that cannot meter fails closed.
"""

from __future__ import annotations

import types
import uuid

import pytest
from sm_ai import metering
from sm_ai.contracts import consume_requests


def _needs_billing() -> None:
    pytest.importorskip("sm_billing.contracts.metering")


async def _seed(factory, limit: int) -> str:
    from sm_billing.constants import PricingModel
    from sm_billing.models import Plan, Subscription
    from sm_billing.plans import seed_default_plan

    await seed_default_plan(factory)
    tenant = uuid.uuid4().hex
    async with factory() as s:
        plan = Plan(
            key=f"p-{tenant[:8]}",
            name="AI",
            pricing_model=PricingModel.FLAT,
            limits={"ai.requests": limit},
        )
        s.add(plan)
        await s.flush()
        s.add(Subscription(tenant_id=tenant, plan_id=plan.id))
        await s.commit()
    return tenant


@pytest.fixture
async def billing_db(tmp_path, monkeypatch):
    _needs_billing()
    from simple_module_db import init_db
    from sm_billing.models import Base

    url = f"sqlite+aiosqlite:///{tmp_path / 'host.db'}"
    state = init_db(url)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setenv("SM_DATABASE_URL", url)
    yield state.session_factory
    await metering.dispose_worker_engine()
    await state.engine.dispose()


async def test_unmetered_without_billing(billing_absent):
    """No ``sm_billing`` at all: nothing is metered (runs with or without billing)."""
    assert await consume_requests("t", idempotency_key="k", source="images:test") is True


@pytest.fixture
def billing_absent(monkeypatch):
    """What a checkout without ``sm_billing`` looks like to the module."""
    monkeypatch.setattr(metering, "find_spec", lambda name: None)


@pytest.fixture
def billing_present(monkeypatch):
    """An installed billing, whether or not this checkout has one."""
    monkeypatch.setattr(metering, "billing_installed", lambda: True)


async def test_an_installed_billing_without_the_entry_fails_closed(monkeypatch, billing_present):
    monkeypatch.setattr(metering, "_billing_contract", lambda: types.SimpleNamespace())
    with pytest.raises(RuntimeError, match="usage_meter"):
        await consume_requests("t", idempotency_key="k", source="images:test")


async def test_a_broken_billing_import_fails_closed(monkeypatch, billing_present):
    def broken():
        raise ImportError("sm_billing is half installed")

    monkeypatch.setattr(metering, "_billing_contract", broken)
    with pytest.raises(ImportError):
        await consume_requests("t", idempotency_key="k", source="images:test")


async def test_charges_through_the_callers_session_factory(billing_db):
    tenant = await _seed(billing_db, 1)
    kw = {"source": "images:test", "session_factory": billing_db}
    assert await consume_requests(tenant, idempotency_key="k1", **kw) is True
    assert await consume_requests(tenant, idempotency_key="k2", **kw) is False
    # A retry of the first call (same key) is a replay: admitted, not counted again.
    assert await consume_requests(tenant, idempotency_key="k1", **kw) is True


async def test_a_bare_worker_opens_its_own_engine(billing_db):
    """No factory and no app: the host's ``SM_DATABASE_URL``, as a worker sees it."""
    tenant = await _seed(billing_db, 2)
    assert await consume_requests(tenant, 2, idempotency_key="w1", source="images:test") is True
    assert await consume_requests(tenant, idempotency_key="w2", source="images:test") is False


@pytest.mark.parametrize("qty", [0, -1, True, 1.5])
async def test_qty_is_validated(qty):
    with pytest.raises(ValueError):
        await consume_requests("t", qty, idempotency_key="k", source="s")


async def test_an_empty_key_is_refused():
    with pytest.raises(ValueError):
        await consume_requests("t", idempotency_key="", source="s")
