from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from conftest import make_user
from helpers import make_plan, make_tenant
from sm_billing import subjects
from sm_billing.metering.validate import check_call
from sm_billing.models import (
    Customer,
    Subscription,
    UsageEvent,
    UsageGauge,
    UsageHold,
    UsagePeriod,
)
from sqlalchemy import select


def test_round_trip():
    uid = uuid.uuid4()
    user = subjects.subject_for_user(uid)
    assert user == f"user:{uid}"
    assert len(user) == 41
    assert subjects.subject_for_user(str(uid)) == user
    assert subjects.kind(user) == "user"
    assert subjects.user_id_of(user) == str(uid)
    assert subjects.tenant_of(user) == "default"

    for tenant in ("default", uuid.uuid4().hex):
        assert subjects.subject_for_tenant(tenant) == tenant
        assert subjects.kind(tenant) == "tenant"
        assert subjects.user_id_of(tenant) is None
        assert subjects.tenant_of(tenant) == tenant


def test_subject_mode_reads_app_state():
    class State:
        pass

    class App:
        state = State()

    assert subjects.subject_mode(App) == "tenant"
    App.state.billing_subject_mode = "user"
    assert subjects.subject_mode(App) == "user"


def test_width_limits():
    check_call("u" * 64, "m", 1, "k", "s")
    with pytest.raises(ValueError):
        check_call("u" * 65, "m", 1, "k", "s")


async def test_exists_and_names(app):
    async with app.state.sm.db.session_factory() as db:
        tenant = await make_tenant(db, "acme")
        await db.commit()
        tenant_id = tenant.id
    user_id = await make_user(app, "who@x.io")
    missing = subjects.subject_for_user(uuid.uuid4())
    user_subject = subjects.subject_for_user(user_id)
    async with app.state.sm.db.session_factory() as db:
        assert await subjects.exists(db, "default")
        assert await subjects.exists(db, tenant_id)
        assert not await subjects.exists(db, uuid.uuid4().hex)
        assert await subjects.exists(db, user_subject)
        assert not await subjects.exists(db, missing)
        assert not await subjects.exists(db, "user:not-a-uuid")

        got = await subjects.names(db, ["default", tenant_id, user_subject, missing])
        assert got == {
            "default": ("default", ""),
            tenant_id: ("Acme", "acme"),
            user_subject: ("who@x.io", ""),
            missing: (missing, ""),
        }


async def test_user_subject_fits_every_table(app):
    subject = subjects.subject_for_user(uuid.uuid4())
    assert len(subject) == 41
    now = datetime.now(UTC)
    async with app.state.sm.db.session_factory() as db:
        plan = await make_plan(db, "wide")
        rows = [
            Customer(tenant_id=subject, provider="manual"),
            Subscription(tenant_id=subject, plan_id=plan.id),
            UsageEvent(
                tenant_id=subject,
                meter="m",
                quantity=1,
                kind="consume",
                idempotency_key="k",
                occurred_at=now,
                source="s",
            ),
            UsagePeriod(tenant_id=subject, meter="m", period_start=now, period_end=now),
            UsageGauge(tenant_id=subject, meter="m"),
            UsageHold(
                id=uuid.uuid4().hex,
                tenant_id=subject,
                meter="m",
                quantity=1,
                status="held",
                idempotency_key="k",
                source="s",
            ),
        ]
        db.add_all(rows)
        await db.commit()
        for row in rows:
            model = type(row)
            found = (await db.execute(select(model).where(model.tenant_id == subject))).scalar_one()
            assert found.tenant_id == subject
