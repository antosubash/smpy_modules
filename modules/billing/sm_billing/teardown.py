"""What deleting a tenant does to its billing (#92, upstream #491).

``tenants`` publishes ``TenantDeleted`` after the commit that removed the
tenant (framework 0.0.38, ``TenantService.delete_tenant``), and
:mod:`sm_billing.tenant_deleted` hands it here. Billing then:

1. expires the tenant's open Checkout session, so it can no longer be paid;
2. cancels at the provider, *immediately* (not at period end), every
   subscription of the tenant's customer whose status has not ended
   (``constants.PROVIDER_CANCELABLE_STATUSES``, every page of them) — the
   mirrored one and any a webhook has not mirrored yet;
3. re-fetches the mirrored subscription through ``sync.resync``, so the local
   row turns ``canceled`` from the provider's own answer;
4. stamps ``Customer.teardown_done_at`` once all of that succeeded.

**The billing rows are kept, for audit.** ``billing_subscription`` (now
``canceled``), ``billing_customer`` and ``billing_webhook_event`` stay; the
customer row is what maps a late Stripe webhook for the deleted tenant back to
its row. A subscription that never reached a provider is marked ``canceled``
directly; its customer's provider subscriptions, if any, are still canceled.

**Retries.** A failure is logged, never raised into the delete. Every run of
this goes through :func:`sm_billing.sweep.run_teardown`, which owns the due
check and the failure count, so the ``TenantDeleted`` handler, ``reconcile_one``
(a mirrored subscription whose tenant is gone) and the sweep share one backoff.
:mod:`sm_billing.sweep` runs it for every customer whose
tenant is gone and whose ``teardown_done_at`` is unset — which covers a
customer with nothing mirrored and an open checkout. Once stamped, a customer
costs the sweep nothing, and a later pass here only checks the mirrored
subscription (one a checkout paid at the last moment may have created).

**Idempotent.** A tenant with no billing is a no-op; an ended subscription is
not canceled again; a cancel the provider refuses because the subscription
ended meanwhile (a concurrent reconcile, Stripe canceling it) counts as done;
a second ``TenantDeleted`` changes nothing. The checkout id is forgotten only
once the provider says the session is no longer open.

**"Not found" is retried, never terminal.** Stripe answers ``resource_missing``
for an object of another account or mode, so a key briefly switched (live to
test, or another account) would read a live customer as gone. Such a failure
backs off like any other (:mod:`sm_billing.sweep`, capped at a day) with a
warning naming the likely cause, and resumes once the right key is back. An
organisation whose Stripe customer really was deleted is therefore retried
once a day, logged each time, until an operator stamps
``billing_customer.teardown_done_at``.

**Single-tenant hosts never tear down a tenant.** Everything there is
``"default"`` with no tenant row; ``"default"`` is refused everywhere. A user
subject (``user:<id>``, #274) is torn down on ``UserDeleted`` through the same
claim and cancel path, bound to ``"default"``; ``TenantDeleted`` refuses one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from simple_module_db import finalize_session, tenant_context
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import select

from sm_billing import constants as c
from sm_billing.contracts.provider import ProviderError
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.models import Customer, Subscription
from sm_billing.subjects import kind, tenant_of
from sm_billing.sync import SyncError, resync

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import BillingProvider

logger = logging.getLogger(__name__)

#: Checkout session status that can still be paid.
_OPEN = "open"


@dataclass(frozen=True)
class _State:
    at_provider: bool  # a mirrored subscription or a provider customer
    done: bool  # a full teardown already succeeded


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
        # provider which it is; anything still open (or unknown) is retried. A
        # session it cannot find raises here: retried, never assumed gone.
        if (await provider.fetch_checkout(session_id)).status in (_OPEN, None):
            raise
    customer.checkout_session_id = None


async def _cancel_one(provider: BillingProvider, subscription_id: str) -> None:
    try:
        await provider.cancel_now(subscription_id)
    except ProviderError:
        # Refused because it ended meanwhile (another canceler won)? Then done.
        snap = await provider.fetch_subscription(subscription_id)
        if snap.status not in c.PROVIDER_ENDED_STATUSES:
            raise


async def _cancel(
    session: AsyncSession,
    provider: BillingProvider,
    app: FastAPI,
    tenant_id: str,
    *,
    full: bool,
    stamp: bool,
) -> list[str]:
    """Cancel and resync; ``full`` also lists the customer, ``stamp`` marks it done.

    "No such object" (``ProviderNotFound``) is raised like any failure, never
    read as "nothing left to bill": Stripe hides objects from a key of another
    account or mode, so a briefly wrong key would otherwise finish a live
    customer's teardown for good.
    """
    sub, customer = await _rows(session, tenant_id)
    ids: list[str] = []
    if full and customer is not None and customer.provider_customer_id:
        ids = await provider.live_subscription_ids(
            customer.provider_customer_id, c.PROVIDER_CANCELABLE_STATUSES
        )
    mirrored = sub.provider_subscription_id if sub is not None else None
    if mirrored and mirrored not in ids:
        snap = await provider.fetch_subscription(mirrored)
        if snap.status not in c.PROVIDER_ENDED_STATUSES:
            ids.append(mirrored)
    for subscription_id in ids:
        await _cancel_one(provider, subscription_id)
    if sub is not None and mirrored:
        try:
            await resync(session, app, provider, mirrored)
        except SyncError as exc:
            # Tenant gone and no customer row maps the snapshot back (an
            # admin-imported row), so apply_snapshot cannot place it. Mark it
            # canceled only once the provider itself says it ended — never on
            # the strength of our own cancel call — rather than fail every
            # tick for good, with no customer row to carry a backoff.
            if exc.code != "unknown_tenant":
                raise
            snap = await provider.fetch_subscription(mirrored)
            if snap.status not in c.PROVIDER_ENDED_STATUSES:
                raise
            sub.status = c.SubscriptionStatus.CANCELED
    if stamp and customer is not None:
        customer.teardown_done_at = datetime.now(UTC)
        # The backoff (attempts, next due) is cleared by the token-conditional
        # ``teardown_claim.succeeded`` once this run returns — never here, where
        # a run whose lease lapsed would reset the count of the run that took over.
    return ids


async def _mark_local(session: AsyncSession, tenant_id: str) -> _State:
    """Cancel a subscription that never reached a provider; report what is left."""
    sub, customer = await _rows(session, tenant_id)
    if sub is not None and sub.provider_subscription_id is None:
        sub.status = c.SubscriptionStatus.CANCELED
    has_customer = customer is not None and bool(customer.provider_customer_id)
    return _State(
        at_provider=has_customer or (sub is not None and bool(sub.provider_subscription_id)),
        done=customer is not None and customer.teardown_done_at is not None,
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
    them, with the session id kept and ``teardown_done_at`` unset for the
    retry. Each step is bound to the tenant and ended with
    ``finalize_session``, never ``commit()``.
    """
    is_user = kind(tenant_id) == c.SUBJECT_MODE_USER
    if tenant_id == DEFAULT_TENANT_ID or not (is_user or is_multi_tenant(app)):
        # No tenant is ever deleted here; "default" missing a row is normal.
        logger.warning("billing: refusing to tear down %s on a single-tenant host", tenant_id)
        return []
    with tenant_context(tenant_of(tenant_id)):
        state = await _step(app, lambda s: _mark_local(s, tenant_id))
        if not state.at_provider:
            return []
        provider = _provider(app, tenant_id)
        if provider is None:
            return []
        full = not state.done
        expire_error: Exception | None = None
        if full:

            async def expire(session: AsyncSession) -> None:
                row = await session.get(Customer, tenant_id)
                if row is not None:
                    await _expire_checkout(provider, row)

            try:
                await _step(app, expire)
            except Exception as exc:
                expire_error = exc
        # Never stamped done while the checkout may still be paid.
        stamp = full and expire_error is None
        canceled = await _step(
            app, lambda s: _cancel(s, provider, app, tenant_id, full=full, stamp=stamp)
        )
    if canceled:
        logger.info("billing: canceled %s for deleted tenant %s", ", ".join(canceled), tenant_id)
    if expire_error is not None:
        raise expire_error
    return canceled
