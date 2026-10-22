"""Row builders shared by the billing tests."""

from __future__ import annotations

from typing import Any

from sm_billing.constants import PricingModel
from sm_billing.models import Plan, Subscription
from tenants.models import Membership, Tenant


async def make_tenant(session, slug: str = "acme", *, members: int = 0) -> Tenant:
    tenant = Tenant(slug=slug, name=slug.title())
    session.add(tenant)
    await session.flush()
    for i in range(members):
        session.add(Membership(tenant_id=tenant.id, user_id=f"u{i}-{slug}", role="member"))
    await session.flush()
    return tenant


async def make_plan(session, key: str = "team", **kw: Any) -> Plan:
    fields: dict[str, Any] = {
        "name": key.title(),
        "pricing_model": PricingModel.FLAT,
        "currency": "eur",
        "stripe_price_month": f"price_{key}_m",
        "stripe_price_year": f"price_{key}_y",
    }
    fields.update(kw)
    plan = Plan(key=key, **fields)
    session.add(plan)
    await session.flush()
    return plan


async def make_sub(session, tenant: Tenant, plan: Plan, **kw: Any) -> Subscription:
    sub = Subscription(tenant_id=tenant.id, plan_id=plan.id, **kw)
    session.add(sub)
    await session.flush()
    return sub


async def store_settings(app, **values: Any) -> None:
    """Persist billing settings and set them in memory, publishing nothing.

    A worker's state after a save it took, minus the rebuild: for tests that
    set up an in-between state (stripe chosen, manual running). Writing the
    database too keeps ``live.ensure_current`` from reverting it on the next
    request, as it reverts a value only one worker holds.
    """
    from settings.hydrate import value_type_for_field
    from settings.service import SettingService
    from settings.store import SettingsStore
    from simple_module_db import finalize_session
    from sm_billing.constants import PACKAGE

    services = getattr(app.state, PACKAGE)
    cls = type(services.settings)
    async with app.state.sm.db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        for field, value in values.items():
            await store.set_override(PACKAGE, field, str(value), value_type_for_field(cls, field))
        await finalize_session(session)
    services.settings = services.settings.model_copy(update=values)
