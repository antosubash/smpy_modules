"""What deleting a tenant does to its billing (#92, upstream #491).

``tenants`` publishes ``TenantDeleted`` after the commit that removed the
tenant (framework 0.0.38, ``TenantService.delete_tenant``). Billing then:

1. expires the tenant's open Checkout session, so it can no longer be paid;
2. cancels at the provider, *immediately* (not at period end), every
   subscription of the tenant's customer that still bills or grants access —
   the mirrored one and any a webhook has not mirrored yet;
3. re-fetches the mirrored subscription through ``sync.resync``, so the local
   row turns ``canceled`` from the provider's own answer, never from an
   assumption about what the cancel did.

**The billing rows are kept, for audit.** ``billing_subscription`` (now
``canceled``), ``billing_customer`` and ``billing_webhook_event`` stay; nothing
reads them for a tenant that no longer exists, and the customer row is what
maps a late Stripe webhook for the deleted tenant back to its row. A
subscription that never reached a provider (assigned by an admin, or written
under ``manual``) is marked ``canceled`` directly: the local row *is* its state.

Every step is idempotent: a tenant with no subscription is a no-op, a
subscription already canceled is not canceled twice, and a second
``TenantDeleted`` changes nothing. A provider failure is logged, never raised —
the tenant is already gone — and the next reconcile retries it:
``reconcile.reconcile_one`` sends a subscription whose tenant no longer exists
here instead of re-applying it.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from simple_module_db import finalize_session, tenant_context
from sqlalchemy import select

from sm_billing import constants as c
from sm_billing.contracts.provider import ProviderError
from sm_billing.models import Customer, Subscription
from sm_billing.sync import resync

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import BillingProvider

logger = logging.getLogger(__name__)

#: Provider statuses that still bill or grant access — what has to be canceled.
LIVE_STATUSES = frozenset({"trialing", "active", "past_due", "unpaid", "incomplete", "paused"})


async def _live_ids(
    provider: BillingProvider, customer: Customer | None, sub: Subscription | None
) -> list[str]:
    """Every subscription id of the tenant the provider still bills."""
    ids: list[str] = []
    if customer is not None and customer.provider_customer_id:
        ids = list(await provider.live_subscription_ids(customer.provider_customer_id))
    mirrored = sub.provider_subscription_id if sub is not None else None
    if mirrored and mirrored not in ids:
        snap = await provider.fetch_subscription(mirrored)
        if snap.status in LIVE_STATUSES:
            ids.append(mirrored)
    return ids


async def _cancel(session: AsyncSession, app: FastAPI, tenant_id: str) -> list[str]:
    provider = getattr(app.state, c.PACKAGE).provider
    sub = (
        await session.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    ).scalar_one_or_none()
    customer = await session.get(Customer, tenant_id)
    if sub is not None and sub.provider_subscription_id is None:
        sub.status = c.SubscriptionStatus.CANCELED
        return []
    if sub is None and (customer is None or not customer.provider_customer_id):
        return []
    if provider is None or not provider.supports_checkout:
        logger.warning(
            "billing: tenant %s was deleted with a customer at the provider, but the "
            "running provider is %s; cancel any subscription it has at the provider",
            tenant_id,
            getattr(provider, "name", "none"),
        )
        return []
    if customer is not None and customer.checkout_session_id:
        with contextlib.suppress(ProviderError):  # already completed or expired
            await provider.expire_checkout(customer.checkout_session_id)
        customer.checkout_session_id = None
    canceled = await _live_ids(provider, customer, sub)
    for subscription_id in canceled:
        await provider.cancel_now(subscription_id)
    if sub is not None and sub.provider_subscription_id:
        await resync(session, app, provider, sub.provider_subscription_id)
    return canceled


async def cancel_for_deleted_tenant(app: FastAPI, tenant_id: str) -> list[str]:
    """Cancel what ``tenant_id`` still pays for; returns the ids canceled.

    Raises a provider failure; the event handler and reconcile catch it.
    Bound to the tenant and ended with ``finalize_session`` like every other
    billing write outside a request.
    """
    with tenant_context(tenant_id):
        async with app.state.sm.db.session_factory() as session:
            canceled = await _cancel(session, app, tenant_id)
            await finalize_session(session)
    if canceled:
        logger.info("billing: canceled %s for deleted tenant %s", ", ".join(canceled), tenant_id)
    return canceled


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Subscribe to ``TenantDeleted`` where the installed ``tenants`` has it.

    Imported defensively rather than raising billing's floor: the event and
    ``delete_tenant`` arrived together in ``simple_module_tenants`` 0.0.38, so
    an older host cannot delete a tenant and has nothing to subscribe to.
    """
    try:
        from tenants.contracts.events import TenantDeleted
    except ImportError:
        return

    async def _on_deleted(event: TenantDeleted) -> None:
        from sm_billing.live import ensure_current

        try:
            await ensure_current(app)  # not through a provider another worker replaced
            await cancel_for_deleted_tenant(app, event.tenant_id)
        except Exception:
            logger.warning(
                "billing: could not cancel the subscription of deleted tenant %s; the next "
                "reconcile retries it (scheduled only if reconcile_interval_minutes is set)",
                event.tenant_id,
                exc_info=True,
            )

    bus.subscribe(TenantDeleted, _on_deleted)
