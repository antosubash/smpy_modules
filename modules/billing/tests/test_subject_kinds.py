"""Lifecycle, sync, sweep, reconcile, seats and checkout tell a user subject
from a tenant one (#274): a user is never suspended, never swept as a deleted
tenant, never bound as a tenant, and never sold a per-seat plan."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import replace

import pytest
from api_helpers import arm_csrf
from conftest import make_user
from fake_provider import FakeProvider
from helpers import make_plan, make_tenant
from simple_module_db import finalize_session
from simple_module_db import tenant_context as real_tenant_context
from sm_billing import reconcile as reconcile_mod
from sm_billing import teardown
from sm_billing.lifecycle import tenant_gone
from sm_billing.models import Customer, Subscription
from sm_billing.reconcile import reconcile
from sm_billing.resolve import effective_plan
from sm_billing.seats import push_quantity
from sm_billing.subjects import subject_for_user
from sm_billing.sync import SyncError, apply_snapshot, resync
from sqlalchemy import select
from subscription_helpers import _snap


def _fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _subscribed(app, subject: str, *, pricing_model="flat", **kw) -> int:
    """``subject`` on a ``team`` plan mirrored as ``sub_1`` (customer ``cus_1``)."""
    async with app.state.sm.db.session_factory() as session:
        plan = await make_plan(session, "team", pricing_model=pricing_model)
        fields = {"provider_subscription_id": "sub_1", **kw}
        session.add(Subscription(tenant_id=subject, plan_id=plan.id, **fields))
        session.add(Customer(tenant_id=subject, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()
        return plan.id


@contextmanager
def _capture(monkeypatch, module, seen: list[str]):
    def spy(tenant_id):
        seen.append(tenant_id)
        return real_tenant_context(tenant_id)

    monkeypatch.setattr(module, "tenant_context", spy)
    yield


async def test_unpaid_user_subscription_downgrades_without_suspension(user_mode_app, status_events):
    app = user_mode_app
    fake = _fake(app)
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject, status="unpaid")
    async with app.state.sm.db.session_factory() as session:
        sub = await resync(session, app, fake, "sub_1")
        await finalize_session(session)
    assert (sub.status, sub.suspended_by_billing) == ("unpaid", False)
    async with app.state.sm.db.session_factory() as session:
        plan, _ = await effective_plan(session, subject)
        assert plan.key != "team"  # back on the default plan
        assert await tenant_gone(session, app, subject) is False
    assert status_events == []  # nothing was suspended


async def test_sync_maps_a_user_subject_via_customer_row(user_mode_app):
    app = user_mode_app
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await _subscribed(app, subject)
    # Metadata missing: the customer row maps the snapshot back to the user.
    async with app.state.sm.db.session_factory() as session:
        sub = await apply_snapshot(session, app, _snap(None), provider="stripe")
        assert sub.tenant_id == subject
        await session.rollback()


async def test_sync_maps_a_user_subject_by_metadata(user_mode_app):
    app = user_mode_app
    subject = subject_for_user(await make_user(app, "a@x.io"))
    async with app.state.sm.db.session_factory() as session:
        await make_plan(session, "team")
        await session.commit()
    # No customer row yet (the first webhook after checkout): the user row is enough.
    async with app.state.sm.db.session_factory() as session:
        sub = await apply_snapshot(session, app, _snap(subject), provider="stripe")
        assert sub.tenant_id == subject
        assert (await session.get(Customer, subject)).provider_customer_id == "cus_1"
        await session.rollback()
    # A user that does not exist, with nothing to map it by, is refused.
    stranger = replace(_snap(subject_for_user(uuid.uuid4())), customer_id="cus_none")
    async with app.state.sm.db.session_factory() as session:
        with pytest.raises(SyncError) as exc:
            await apply_snapshot(session, app, stranger, provider="stripe")
    assert exc.value.code == "unknown_tenant"


async def test_sweep_ignores_user_subjects(app):
    """A user-subject customer left from a mode switch is no deleted tenant."""
    fake = _fake(app)
    subject = subject_for_user(uuid.uuid4())
    async with app.state.sm.db.session_factory() as session:
        session.add(Customer(tenant_id=subject, provider="stripe", provider_customer_id="cus_u"))
        await session.commit()
    report = await reconcile(app)
    assert (report.torn_down, report.errors, fake.calls) == (0, [], [])
    async with app.state.sm.db.session_factory() as session:
        customer = await session.get(Customer, subject)
        assert (customer.teardown_attempts, customer.teardown_done_at) == (0, None)
        assert await tenant_gone(session, app, subject) is False


async def test_tenant_deleted_refuses_a_user_subject(app):
    from tenants.contracts.events import TenantDeleted

    fake = _fake(app)
    subject = subject_for_user(uuid.uuid4())
    await _subscribed(app, subject)
    await app.state.sm.event_bus.publish(TenantDeleted(tenant_id=subject, slug="x", name="X"))
    assert fake.calls == []
    async with app.state.sm.db.session_factory() as session:
        assert (await session.get(Customer, subject)).teardown_attempts == 0


async def test_reconcile_binds_the_subjects_tenant(user_mode_app, monkeypatch):
    app = user_mode_app
    fake = _fake(app)
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject)
    seen: list[str] = []
    with _capture(monkeypatch, reconcile_mod, seen):
        report = await reconcile(app)
    assert (report.synced, report.errors) == (1, [])
    assert seen == ["default"]


async def test_teardown_of_a_user_subject_binds_default(user_mode_app, monkeypatch):
    """The shared cancel path (``UserDeleted`` uses it) runs for a user subject."""
    app = user_mode_app
    fake = _fake(app)
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = replace(_snap(subject), customer_id="cus_1")
    seen: list[str] = []
    with _capture(monkeypatch, teardown, seen):
        canceled = await teardown.cancel_for_deleted_tenant(app, subject)
    assert canceled == ["sub_1"]
    assert seen == ["default"]


async def test_per_seat_plan_refused_for_user(user_mode_app, user_client):
    app = user_mode_app
    fake = _fake(app)
    async with app.state.sm.db.session_factory() as session:
        seats = (await make_plan(session, "seats", pricing_model="per_seat")).id
        await session.commit()
    async with user_client("a@x.io") as (client, user_id):
        await arm_csrf(client)
        response = await client.post("/api/billing/checkout", json={"plan_id": seats})
        assert (response.status_code, response.json()["detail"]) == (
            422,
            "per_seat_requires_tenant",
        )
        await _subscribed(app, subject_for_user(user_id))
        changed = await client.post("/api/billing/change-plan", json={"plan_id": seats})
        assert (changed.status_code, changed.json()["detail"]) == (
            422,
            "per_seat_requires_tenant",
        )
    assert fake.called("ensure_customer") == fake.called("create_checkout") == []
    assert fake.called("change_plan") == []


async def test_checkout_names_the_customer_after_the_user(user_mode_app, user_client):
    app = user_mode_app
    fake = _fake(app)
    async with app.state.sm.db.session_factory() as session:
        team = (await make_plan(session, "team")).id
        await session.commit()
    async with user_client("a@x.io") as (client, _):
        await arm_csrf(client)
        response = await client.post("/api/billing/checkout", json={"plan_id": team})
        assert response.status_code == 200, response.text
    assert fake.called("ensure_customer")[0]["name"] == "a@x.io"


async def test_seat_push_skips_user_subjects(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    subject = subject_for_user(await make_user(app, "a@x.io"))
    await _subscribed(app, subject, pricing_model="per_seat", quantity=3)
    assert await push_quantity(app, subject) is False
    assert fake.called("set_quantity") == []
    async with app.state.sm.db.session_factory() as session:
        stmt = select(Subscription.quantity).where(Subscription.tenant_id == subject)
        assert (await session.execute(stmt)).scalar_one() == 3


async def test_sync_never_trusts_default_metadata_on_a_multi_tenant_host(app):
    """``"default"`` is no tenant there: the customer row decides, or nothing does."""
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session, "acme")
        await make_plan(session, "team")
        session.add(Customer(tenant_id=tenant.id, provider="stripe", provider_customer_id="cus_1"))
        await session.commit()
        tenant_id = tenant.id
    async with app.state.sm.db.session_factory() as session:
        sub = await apply_snapshot(session, app, _snap("default"), provider="stripe")
        assert sub.tenant_id == tenant_id
        assert await session.get(Customer, "default") is None
        await session.rollback()
    orphan = replace(_snap("default"), customer_id="cus_none")
    async with app.state.sm.db.session_factory() as session:
        with pytest.raises(SyncError) as exc:
            await apply_snapshot(session, app, orphan, provider="stripe")
    assert exc.value.code == "unknown_tenant"
