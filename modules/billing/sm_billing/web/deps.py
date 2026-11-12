"""FastAPI dependencies for the billing routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_core.environments import NON_PROD_ENVIRONMENTS
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from tenants.web.deps import ActiveTenantContext, require_active_tenant, require_user_id

from sm_billing.core import constants as c
from sm_billing.core.context import BillingContext, billing_context, is_user_mode, user_context
from sm_billing.core.errors import BillingError
from sm_billing.web.services.checkout import BillingService


async def require_active(request: Request) -> ActiveTenantContext:
    """The active tenant; in user mode the signed-in user's own subject.

    A single-tenant host never sets ``tenant_role``, so user mode cannot go
    through ``require_active_tenant``.
    """
    if not is_user_mode(request):
        return await require_active_tenant(request)
    ctx = user_context(request)
    return ActiveTenantContext(
        tenant_id=ctx.tenant_id, role=ctx.role, user_id=str(request.state.user.id)
    )


ActiveTenant = Annotated[ActiveTenantContext, Depends(require_active)]


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
    """Origin for provider return URLs (Checkout's success/cancel, the portal's
    return): ``return_base_url``.

    Only in development or testing does a blank setting fall back to this
    request's origin (#355). Anywhere else the ``Host`` header is the client's
    choice, and behind a proxy without ``trusted_proxy`` it is the internal host
    name the customer cannot reach, so the session is refused with 409
    ``return_base_url_missing`` before the provider is called. A host that
    reports no environment counts as production.
    """
    configured = (getattr(request.app.state, c.PACKAGE).settings.return_base_url or "").strip()
    if configured:
        return configured.rstrip("/")
    host = getattr(getattr(request.app.state, "sm", None), "settings", None)
    if getattr(host, "environment", None) not in NON_PROD_ENVIRONMENTS:
        raise BillingError("return_base_url_missing", 409)
    return str(request.base_url).rstrip("/")


def user_email(request: Request) -> str | None:
    return getattr(getattr(request.state, "user", None), "email", None)


async def get_context(request: Request, db: AsyncSession = Depends(get_db)) -> BillingContext:
    """Active tenant, or a billing-suspended one its owner is restoring.

    User mode: the signed-in user, else 401 ``subject_required``."""
    if is_user_mode(request):
        return user_context(request)
    await require_user_id(request)
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
