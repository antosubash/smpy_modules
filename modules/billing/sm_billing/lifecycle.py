"""What a subscription's status does to its tenant.

``decide`` is the whole policy as a pure function; ``apply_lifecycle`` carries
it out through ``TenantService.set_status`` so the tenants module publishes
``TenantStatusChanged`` and drops its membership cache exactly as an admin
suspension would.

- trialing / active / past_due / canceled / incomplete: reactivate the tenant
  *only if billing suspended it*. An admin's suspension is never lifted here.
- unpaid: suspend an active tenant and remember that billing did it. A tenant
  an admin already suspended stays theirs.

A user subject (``user:<id>``, #274) has no tenant to suspend: an unpaid
subscription only drops it to the default plan (``resolve.effective_plan``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from simple_module_db.tenancy import DEFAULT_TENANT_ID
from tenants.constants import TenantStatus
from tenants.models import Tenant
from tenants.resolver import make_invalidator
from tenants.service import TenantService
from users.models import User

from sm_billing import constants as c
from sm_billing.constants import SubscriptionStatus
from sm_billing.subject_keys import kind, subject_mode, user_uuid

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


def is_multi_tenant(app: FastAPI) -> bool:
    """Whether the host runs with ``multi_tenant`` on (tenants have rows)."""
    return getattr(getattr(app.state.sm, "settings", None), "multi_tenant", False) is True


async def tenant_gone(db: AsyncSession, app: FastAPI, tenant_id: str) -> bool:
    """Whether ``tenant_id`` was deleted: its ``tenants_tenant`` row is missing.

    Never on a single-tenant host, where everything runs as ``"default"`` and
    no row exists for it — a missing row there is normal, not a deletion, and
    reading it as one would cancel the host's own subscription. Never for
    ``"default"`` either, for a host that switched multi-tenancy on later.

    A user subject (#274) has no tenant row. In user mode it is "gone" once its
    ``users_user`` row is (users are hard-deleted): reconcile then routes it to
    the teardown, which is the retry for a ``UserDeleted`` cancel that failed.
    In tenant mode a left-over ``user:<id>`` is never gone.
    """
    if kind(tenant_id) == c.SUBJECT_MODE_USER:
        if subject_mode(app) != c.SUBJECT_MODE_USER:
            return False
        user_id = user_uuid(tenant_id)  # a non-canonical spelling names no user
        return user_id is not None and await db.get(User, user_id) is None
    if not is_multi_tenant(app) or tenant_id == DEFAULT_TENANT_ID:
        return False
    return await db.get(Tenant, tenant_id) is None


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
    if kind(sub.tenant_id) == c.SUBJECT_MODE_USER:
        # Never suspended: a user is not a tenant.
        sub.suspended_by_billing = False
        await db.flush()
        return
    service = tenant_service(db, app)
    tenant = await db.get(Tenant, sub.tenant_id)
    if tenant is None:
        return
    actions = decide(sub.status, sub.suspended_by_billing, tenant.status)
    sub.suspended_by_billing = actions.suspended_by_billing
    if actions.set_status is not None:
        await service.set_status(tenant.id, actions.set_status)
    await db.flush()
