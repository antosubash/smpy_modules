"""What a subscription's status does to its tenant.

``decide`` is the whole policy as a pure function; ``apply_lifecycle`` carries
it out through ``TenantService.set_status`` so the tenants module publishes
``TenantStatusChanged`` and drops its membership cache exactly as an admin
suspension would.

- trialing / active / past_due / canceled / incomplete: reactivate the tenant
  *only if billing suspended it*. An admin's suspension is never lifted here.
- unpaid: suspend an active tenant and remember that billing did it. A tenant
  an admin already suspended stays theirs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tenants.constants import TenantStatus
from tenants.models import Tenant
from tenants.resolver import make_invalidator
from tenants.service import TenantService

from sm_billing.constants import SubscriptionStatus

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.models import Subscription


@dataclass(frozen=True)
class Actions:
    set_status: TenantStatus | None
    suspended_by_billing: bool


def decide(status: str, suspended_by_billing: bool, tenant_status: str) -> Actions:
    if status == SubscriptionStatus.UNPAID:
        if tenant_status == TenantStatus.ACTIVE:
            return Actions(TenantStatus.SUSPENDED, True)
        return Actions(None, suspended_by_billing)
    if suspended_by_billing and tenant_status == TenantStatus.SUSPENDED:
        return Actions(TenantStatus.ACTIVE, False)
    return Actions(None, False)


def tenant_service(db: AsyncSession, app: FastAPI) -> TenantService:
    """A ``TenantService`` wired like ``tenants.deps.get_tenant_service``."""
    return TenantService(
        db,
        bus=app.state.sm.event_bus,
        invalidate=make_invalidator(app),
        entitlements=app.state.tenants.entitlements,
    )


async def apply_lifecycle(db: AsyncSession, app: FastAPI, sub: Subscription) -> None:
    """Apply ``decide`` to ``sub``'s tenant; flushes, never commits.

    The status event is queued with ``db.on_commit`` (every framework session
    is a ``RequestSession``), so a caller outside a request must commit with
    ``simple_module_db.finalize_session`` — a bare ``commit()`` drops it.
    """
    service = tenant_service(db, app)
    tenant = await db.get(Tenant, sub.tenant_id)
    if tenant is None:
        return
    actions = decide(sub.status, sub.suspended_by_billing, tenant.status)
    sub.suspended_by_billing = actions.suspended_by_billing
    if actions.set_status is not None:
        await service.set_status(tenant.id, actions.set_status)
    await db.flush()
