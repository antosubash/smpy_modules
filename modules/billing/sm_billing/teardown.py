"""What deleting a tenant does to its billing (#92, upstream #491).

``tenants`` publishes ``TenantDeleted`` after the commit that removed the
tenant (framework 0.0.38, ``TenantService.delete_tenant``). Billing then:

1. expires the tenant's open Checkout session, so it can no longer be paid;
2. cancels at the provider, *immediately* (not at period end), every
   subscription of the tenant's customer whose status is in
   ``constants.PROVIDER_LIVE_STATUSES`` — the mirrored one and any a webhook
   has not mirrored yet;
3. re-fetches the mirrored subscription through ``sync.resync``, so the local
   row turns ``canceled`` from the provider's own answer, never from an
   assumption about what the cancel did.

**The billing rows are kept, for audit.** ``billing_subscription`` (now
``canceled``), ``billing_customer`` and ``billing_webhook_event`` stay; nothing
reads them for a tenant that no longer exists, and the customer row is what
maps a late Stripe webhook for the deleted tenant back to its row. A
subscription that never reached a provider (assigned by an admin, or written
under ``manual``) is marked ``canceled`` directly: the local row *is* its state.
Its customer's provider subscriptions, if it has any, are still canceled.

Every step is idempotent: a tenant with no billing is a no-op, a subscription
already canceled is not canceled twice, and a second ``TenantDeleted`` changes
nothing. The checkout session id is forgotten only once the session is no
longer open; any other expiry failure keeps it and fails the teardown, after
the subscriptions were still canceled. A failure is logged, never raised into
the delete — the tenant is already gone — and the next reconcile retries it:
``reconcile.reconcile_one`` sends a subscription whose tenant no longer exists
here instead of re-applying it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
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

#: Checkout session status that can still be paid.
_OPEN = "open"


async def _rows(
    session: AsyncSession, tenant_id: str
) -> tuple[Subscription | None, Customer | None]:
    stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
    sub = (await session.execute(stmt)).scalar_one_or_none()
    return sub, await session.get(Customer, tenant_id)


def _provider(app: FastAPI, tenant_id: str) -> BillingProvider | None:
    """The provider to cancel through, or ``None`` (logged) when there is none."""
    provider = getattr(app.state, c.PACKAGE).provider
    if provider is not None and provider.supports_checkout:
        return provider
    logger.warning(
        "billing: tenant %s was deleted with a customer at the provider, but the "
        "running provider is %s; cancel any subscription it has at the provider",
        tenant_id,
        getattr(provider, "name", "none"),
    )
    return None


async def _expire_checkout(provider: BillingProvider, customer: Customer) -> None:
    """Expire the open session; forget its id only once it cannot be paid."""
    session_id = customer.checkout_session_id
    if not session_id:
        return
    try:
        await provider.expire_checkout(session_id)
    except ProviderError:
        # Expiring a completed or already expired session fails too. Ask the
        # provider which it is; anything still open (or unknown) is retried.
        if (await provider.fetch_checkout(session_id)).status in (_OPEN, None):
            raise
    customer.checkout_session_id = None


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
        if snap.status in c.PROVIDER_LIVE_STATUSES:
            ids.append(mirrored)
    return ids


async def _cancel(
    session: AsyncSession, provider: BillingProvider, app: FastAPI, tenant_id: str
) -> list[str]:
    sub, customer = await _rows(session, tenant_id)
    canceled = await _live_ids(provider, customer, sub)
    for subscription_id in canceled:
        await provider.cancel_now(subscription_id)
    if sub is not None and sub.provider_subscription_id:
        await resync(session, app, provider, sub.provider_subscription_id)
    return canceled


async def _mark_local(session: AsyncSession, tenant_id: str) -> bool:
    """Cancel a subscription that never reached a provider; ``True`` if the
    tenant has anything at the provider (a mirrored subscription or a customer).
    """
    sub, customer = await _rows(session, tenant_id)
    if sub is not None and sub.provider_subscription_id is None:
        sub.status = c.SubscriptionStatus.CANCELED
    return bool(
        (sub is not None and sub.provider_subscription_id)
        or (customer is not None and customer.provider_customer_id)
    )


async def _step[T](app: FastAPI, work: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``work(session)`` in its own session, then finalize."""
    async with app.state.sm.db.session_factory() as session:
        result = await work(session)
        await finalize_session(session)
    return result


async def cancel_for_deleted_tenant(app: FastAPI, tenant_id: str) -> list[str]:
    """Cancel what ``tenant_id`` still pays for; returns the ids canceled.

    Raises a provider failure; the event handler and reconcile catch it. A
    failed checkout expiry does not hold up the cancels: it is raised after
    them, with the session id kept for the retry. Each step is bound to the
    tenant and ended with ``finalize_session``, never ``commit()``.
    """
    with tenant_context(tenant_id):
        if not await _step(app, lambda s: _mark_local(s, tenant_id)):
            return []
        provider = _provider(app, tenant_id)
        if provider is None:
            return []

        async def expire(session: AsyncSession) -> None:
            row = await session.get(Customer, tenant_id)
            if row is not None:
                await _expire_checkout(provider, row)

        expire_error: Exception | None = None
        try:
            await _step(app, expire)
        except Exception as exc:
            expire_error = exc
        canceled = await _step(app, lambda s: _cancel(s, provider, app, tenant_id))
    if canceled:
        logger.info("billing: canceled %s for deleted tenant %s", ", ".join(canceled), tenant_id)
    if expire_error is not None:
        raise expire_error
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
