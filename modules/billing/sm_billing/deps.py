"""FastAPI dependencies for the billing routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from tenants.deps import ActiveTenantContext, require_active_tenant, require_user_id

from sm_billing import constants as c
from sm_billing.checkout import BillingService
from sm_billing.context import BillingContext, billing_context
from sm_billing.errors import BillingError

ActiveTenant = Annotated[ActiveTenantContext, Depends(require_active_tenant)]


def require_owner(ctx: ActiveTenant) -> ActiveTenantContext:
    """Money decisions belong to the tenant's owner, not every manager."""
    if ctx.role != c.TENANT_ROLE_OWNER:
        raise BillingError("tenant_owner_required", 403)
    return ctx


Owner = Annotated[ActiveTenantContext, Depends(require_owner)]


def get_billing_service(
    request: Request, ctx: ActiveTenant, db: AsyncSession = Depends(get_db)
) -> BillingService:
    return BillingService(db, request.app, ctx.tenant_id)


BillingServiceDep = Annotated[BillingService, Depends(get_billing_service)]


def base_url(request: Request) -> str:
    """Origin for provider return URLs: the setting, else this request's origin."""
    configured = getattr(request.app.state, c.PACKAGE).settings.return_base_url
    return (configured or str(request.base_url)).rstrip("/")


def user_email(request: Request) -> str | None:
    return getattr(getattr(request.state, "user", None), "email", None)


async def get_context(request: Request, db: AsyncSession = Depends(get_db)) -> BillingContext:
    """Active tenant, or a billing-suspended one its owner is restoring."""
    require_user_id(request)
    ctx = await billing_context(request, db)
    if ctx is None:
        raise BillingError("tenant_required", 403)
    return ctx


Context = Annotated[BillingContext, Depends(get_context)]


def get_context_service(
    request: Request, ctx: Context, db: AsyncSession = Depends(get_db)
) -> BillingService:
    return BillingService(db, request.app, ctx.tenant_id)


ContextServiceDep = Annotated[BillingService, Depends(get_context_service)]
