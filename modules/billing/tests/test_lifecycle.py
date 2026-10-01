from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from helpers import make_plan, make_sub, make_tenant
from sm_billing.constants import SubscriptionStatus as S
from sm_billing.lifecycle import Actions, apply_lifecycle, decide
from tenants.constants import TenantStatus as T
from tenants.contracts.events import TenantStatusChanged
from tenants.models import Tenant

ACTIVE, SUSPENDED = T.ACTIVE, T.SUSPENDED
NOOP_KEEP = Actions(set_status=None, suspended_by_billing=False)


@pytest.mark.parametrize("status", [S.TRIALING, S.ACTIVE, S.PAST_DUE, S.CANCELED, S.INCOMPLETE])
def test_paying_or_fallback_reactivates_what_billing_suspended(status):
    assert decide(status, True, SUSPENDED) == Actions(ACTIVE, False)


@pytest.mark.parametrize("status", [S.TRIALING, S.ACTIVE, S.PAST_DUE, S.CANCELED, S.INCOMPLETE])
def test_admin_suspension_is_never_lifted(status):
    assert decide(status, False, SUSPENDED) == NOOP_KEEP


@pytest.mark.parametrize("status", [S.TRIALING, S.ACTIVE, S.PAST_DUE, S.CANCELED, S.INCOMPLETE])
def test_active_tenant_untouched(status):
    assert decide(status, False, ACTIVE) == NOOP_KEEP


def test_flag_cleared_when_admin_already_reactivated():
    assert decide(S.ACTIVE, True, ACTIVE) == NOOP_KEEP


def test_unpaid_suspends_active_tenant():
    assert decide(S.UNPAID, False, ACTIVE) == Actions(SUSPENDED, True)


def test_unpaid_keeps_billing_suspension():
    assert decide(S.UNPAID, True, SUSPENDED) == Actions(None, True)


def test_unpaid_on_admin_suspended_tenant_does_not_claim_it():
    assert decide(S.UNPAID, False, SUSPENDED) == NOOP_KEEP


async def test_apply_suspends_and_publishes_after_drain(app):
    seen: list[TenantStatusChanged] = []

    async def record(event: TenantStatusChanged) -> None:
        seen.append(event)

    app.state.sm.event_bus.subscribe(TenantStatusChanged, record)
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        sub = await make_sub(session, tenant, await make_plan(session), status=S.UNPAID)
        await apply_lifecycle(session, app, sub)
        await finalize_session(session)
        refreshed = await session.get(Tenant, tenant.id)
        await session.refresh(refreshed)
        assert refreshed.status == SUSPENDED
        assert sub.suspended_by_billing is True
    assert [e.status for e in seen] == [SUSPENDED]


async def test_apply_reactivates(app):
    async with app.state.sm.db.session_factory() as session:
        tenant = await make_tenant(session)
        tenant.status = SUSPENDED
        sub = await make_sub(
            session, tenant, await make_plan(session), status=S.ACTIVE, suspended_by_billing=True
        )
        await apply_lifecycle(session, app, sub)
        assert tenant.status == ACTIVE
        assert sub.suspended_by_billing is False
