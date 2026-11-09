"""Bind the framework-resolved tenant, including on single-tenant hosts."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from simple_module_db import current_tenant_id, is_valid_tenant_id, tenant_context
from simple_module_hosting.tenancy import TenancyMode, tenancy_mode


def resolved(request: Request, missing: int) -> str:
    tenant = getattr(request.state, "tenant_id", None) or current_tenant_id.get()
    if tenant is None and tenancy_mode(request.app) is TenancyMode.SINGLE:
        tenant = "default"
    if not is_valid_tenant_id(tenant):
        raise HTTPException(missing, detail="tenant_required" if missing == 403 else "Not found")
    return tenant


async def bind_admin(request: Request) -> AsyncIterator[str]:
    with tenant_context(resolved(request, 403)) as tenant:
        yield tenant


async def bind_public(request: Request) -> AsyncIterator[str]:
    with tenant_context(resolved(request, 404)) as tenant:
        yield tenant
