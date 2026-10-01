"""Which tenant a billing request is about — including one billing suspended.

The tenants resolver never makes a suspended organisation the active tenant,
which is right everywhere except here: the owner of an organisation billing
suspended for non-payment has to reach the Customer Portal to pay, or the
suspension can never be lifted from inside the app. So when the session's
chosen organisation is suspended *by billing* and the user owns it, billing
opens it in **restore** mode — status and portal only, never checkout or plan
changes. An organisation an admin suspended stays closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenants.constants import SESSION_ACTIVE_TENANT, TenantStatus
from tenants.models import Membership, Tenant

from sm_billing import constants as c
from sm_billing.resolve import subscription_for


@dataclass(frozen=True)
class BillingContext:
    tenant_id: str
    role: str
    restore: bool = False


async def _restorable(request: Request, db: AsyncSession) -> BillingContext | None:
    if not getattr(request.state, "tenant_suspended", False):
        return None
    user = getattr(request.state, "user", None)
    session = request.scope.get("session")
    chosen = session.get(SESSION_ACTIVE_TENANT) if session is not None else None
    if user is None or not chosen:
        return None
    stmt = select(Membership.role).where(
        Membership.tenant_id == chosen, Membership.user_id == str(user.id)
    )
    if (await db.execute(stmt)).scalar_one_or_none() != c.TENANT_ROLE_OWNER:
        return None
    tenant = await db.get(Tenant, chosen)
    if tenant is None or tenant.status != TenantStatus.SUSPENDED:
        return None
    sub = await subscription_for(db, chosen)
    if sub is None or not sub.suspended_by_billing:
        return None
    return BillingContext(tenant_id=chosen, role=c.TENANT_ROLE_OWNER, restore=True)


async def billing_context(request: Request, db: AsyncSession) -> BillingContext | None:
    """The organisation this request bills, or ``None`` (pick one first).

    The chosen-but-suspended organisation wins over the resolver's fallback:
    it is the one the user asked for, and the one that needs paying.
    """
    restore = await _restorable(request, db)
    if restore is not None:
        return restore
    tenant_id = getattr(request.state, "tenant_id", None)
    role = getattr(request.state, "tenant_role", None)
    if tenant_id is None or role is None:
        return None
    return BillingContext(tenant_id=tenant_id, role=role)
