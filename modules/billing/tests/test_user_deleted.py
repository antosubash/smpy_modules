"""Deleting a user tears down their subscription like a deleted tenant's (#274)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from conftest import make_user
from fake_provider import FakeProvider
from simple_module_core.user_events import UserDeleted
from sm_billing.models import Customer
from sm_billing.reconcile import reconcile
from sm_billing.subjects import subject_for_user
from subscription_helpers import _snap
from test_subject_kinds import _subscribed


def _fake(app) -> FakeProvider:
    provider = FakeProvider()
    app.state.sm_billing.provider = provider
    return provider


async def _publish(app, user_id: str) -> None:
    await app.state.sm.event_bus.publish(UserDeleted(user_id=uuid.UUID(user_id)))


async def test_user_deleted_cancels_their_subscription(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    user_id = await make_user(app, "a@x.io")
    subject = subject_for_user(user_id)
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject, status="active", sid="sub_1")

    await _publish(app, user_id)

    assert fake.called("cancel_now") == [{"subscription_id": "sub_1"}]
    async with app.state.sm.db.session_factory() as session:
        customer = await session.get(Customer, subject)
        assert customer is not None and customer.teardown_done_at is not None


async def test_user_deleted_without_customer_is_a_noop(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    await _publish(app, str(uuid.uuid4()))
    assert fake.called("cancel_now") == []


async def test_not_subscribed_in_tenant_mode(app):
    fake = _fake(app)
    user_id = str(uuid.uuid4())
    subject = subject_for_user(user_id)
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject, status="active", sid="sub_1")

    await _publish(app, user_id)

    assert fake.called("cancel_now") == []


# A failed teardown is retried: reconcile for a mirrored subscription, the
# sweep for a customer without one.


async def _customer(app, subject: str) -> Customer | None:
    async with app.state.sm.db.session_factory() as session:
        return await session.get(Customer, subject)


async def _due_now(app, subject: str) -> None:
    async with app.state.sm.db.session_factory() as session:
        customer = await session.get(Customer, subject)
        customer.teardown_next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()


async def _failed_once(app, fake, *, mirrored: bool) -> str:
    """A deleted user (no row) whose first cancel failed."""
    subject = subject_for_user(uuid.uuid4())
    if mirrored:
        await _subscribed(app, subject)
    else:
        async with app.state.sm.db.session_factory() as session:
            customer = Customer(tenant_id=subject, provider="stripe", provider_customer_id="cus_1")
            session.add(customer)
            await session.commit()
        fake.live["cus_1"] = ["sub_1"]
    fake.snapshots["sub_1"] = _snap(subject, status="active", sid="sub_1")
    fake.fail.add("cancel_now")
    await _publish(app, subject.removeprefix("user:"))
    customer = await _customer(app, subject)
    assert customer.teardown_attempts == 1 and customer.teardown_done_at is None
    fake.fail.clear()
    return subject


async def test_reconcile_retries_a_failed_teardown_of_a_mirrored_subscription(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    subject = await _failed_once(app, fake, mirrored=True)
    await reconcile(app)  # backoff: not due yet
    assert len(fake.called("cancel_now")) == 1  # the failed attempt only
    await _due_now(app, subject)
    await reconcile(app)
    assert len(fake.called("cancel_now")) == 2  # failed, then succeeded
    assert (await _customer(app, subject)).teardown_done_at is not None


async def test_the_sweep_retries_a_customer_without_a_subscription(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    subject = await _failed_once(app, fake, mirrored=False)
    await reconcile(app)
    assert len(fake.called("cancel_now")) == 1  # the failed attempt only
    await _due_now(app, subject)
    report = await reconcile(app)
    assert report.torn_down == 1
    assert len(fake.called("cancel_now")) == 2
    assert (await _customer(app, subject)).teardown_done_at is not None


async def test_a_live_user_is_never_torn_down(user_mode_app):
    app = user_mode_app
    fake = _fake(app)
    subject = subject_for_user(await make_user(app, "live@x.io"))
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject, status="active", sid="sub_1")
    await reconcile(app)
    assert fake.called("cancel_now") == []
    assert (await _customer(app, subject)).teardown_done_at is None


async def test_tenant_mode_never_sweeps_user_customers(app):
    fake = _fake(app)
    subject = subject_for_user(uuid.uuid4())
    await _subscribed(app, subject)
    fake.snapshots["sub_1"] = _snap(subject, status="active", sid="sub_1")
    await reconcile(app)
    assert fake.called("cancel_now") == []


async def test_the_user_sweep_is_one_query_however_many_customers(user_mode_app):
    """An anti-join on ``users_user``, not a lookup per paying user."""
    from sm_billing.user_sweep import orphan_users
    from sqlalchemy import event

    app = user_mode_app
    live = [subject_for_user(await make_user(app, f"u{i}@x.io")) for i in range(3)]
    gone = [subject_for_user(uuid.uuid4()) for _ in range(2)]
    odd = "user:" + uuid.uuid4().hex  # non-canonical: names no user, never torn down
    async with app.state.sm.db.session_factory() as session:
        for i, subject in enumerate([*live, *gone, odd]):
            customer = Customer(tenant_id=subject, provider="stripe", provider_customer_id=f"c{i}")
            session.add(customer)
        await session.commit()

    statements: list[str] = []

    def spy(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    engine = app.state.sm.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", spy)
    try:
        found = await orphan_users(app, None, datetime.now(UTC))
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert sorted(found) == sorted(gone)
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1
