"""Deleting a user tears down their subscription like a deleted tenant's (#274)."""

from __future__ import annotations

import uuid

from conftest import make_user
from fake_provider import FakeProvider
from simple_module_core.user_events import UserDeleted
from sm_billing.models import Customer
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
