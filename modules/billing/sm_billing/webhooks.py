"""Webhook processing: verify, deduplicate, re-fetch, sync.

The event payload is never trusted for state. Each handled event re-fetches
the subscription from the provider, so whichever delivery lands last writes
the provider's *current* view — out-of-order delivery is harmless. The
``billing_webhook_event`` row makes a redelivery of a processed event a no-op,
and a failure leaves ``processed_at`` empty and returns 500 so the provider
retries; the retry reprocesses rather than skipping.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from simple_module_db import finalize_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sm_billing.constants import CHECKOUT_COMPLETED, HANDLED_EVENTS
from sm_billing.contracts.provider import InvalidWebhookSignature, ProviderError
from sm_billing.models import Customer
from sm_billing.models import WebhookEvent as EventRow
from sm_billing.seats import push_quantity
from sm_billing.sync import SyncError, apply_snapshot

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

    from sm_billing.contracts.provider import (
        BillingProvider,
        SubscriptionSnapshot,
        WebhookEvent,
    )

logger = logging.getLogger(__name__)

#: SyncError codes that are final, mapped to the response detail.
_ACKNOWLEDGED = {
    "unknown_tenant": "ignored_unknown_tenant",
    "nothing_to_apply": "ignored_nothing_to_apply",
    "customer_mismatch": "ignored_customer_mismatch",
}


async def _claim(app: FastAPI, event: WebhookEvent, provider: str) -> bool:
    """Record the event; ``False`` when it was already processed."""
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, event.id)
        if row is not None:
            return row.processed_at is None
        session.add(EventRow(id=event.id, provider=provider, type=event.type))
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent delivery inserted it first; let that one finish and
            # have the provider retry this one.
            raise ProviderError(f"event {event.id} is being processed") from None
    return True


async def _finish(
    app: FastAPI, event_id: str, error: str | None, *, note: str | None = None
) -> None:
    """Record the outcome. ``error`` leaves it for a retry; ``note`` is kept on
    an event that is done but worth explaining."""
    async with app.state.sm.db.session_factory() as session:
        row = await session.get(EventRow, event_id)
        if row is None:  # pragma: no cover - claimed above
            return
        row.error = error or note
        if error is None:
            row.processed_at = datetime.now(UTC)
        await session.commit()


async def _snapshot(
    provider: BillingProvider, event: WebhookEvent
) -> tuple[SubscriptionSnapshot, bool]:
    """Re-fetch the subscription ``event`` points at; nothing from its payload.

    Returns the snapshot and whether its tenant came from a Checkout's
    ``client_reference_id`` rather than the subscription itself. A subscription
    without a ``tenant_id`` in its metadata is left that way: ``apply_snapshot``
    then finds the tenant through the customer or raises ``unknown_tenant``.
    Only a completed Checkout may supply one, as the provider reports it now.
    """
    if event.type != CHECKOUT_COMPLETED or not event.checkout_id:
        # No session id to re-fetch (a malformed delivery): the subscription
        # alone, never a retrieve("") that would 500 on every redelivery.
        return await provider.fetch_subscription(event.subscription_id or ""), False
    checkout = await provider.fetch_checkout(event.checkout_id)
    if not checkout.subscription_id:
        # Not a subscription checkout after all; no retry makes it one.
        raise SyncError("nothing_to_apply", f"checkout {checkout.id} has no subscription")
    snapshot = await provider.fetch_subscription(checkout.subscription_id)
    if snapshot.tenant_id is not None or checkout.tenant_id is None:
        return snapshot, False
    # Anyone can open a Checkout (a Payment Link) naming any tenant, so the
    # reference only counts when the session and subscription agree on who pays.
    if not checkout.customer_id or checkout.customer_id != snapshot.customer_id:
        raise SyncError("customer_mismatch", f"checkout {checkout.id}")
    return replace(snapshot, tenant_id=checkout.tenant_id), True


async def _check_reference(session: AsyncSession, snapshot: SubscriptionSnapshot) -> None:
    """The reference only binds a customer to a tenant that has none or the same.

    A tenant already billed to another customer is not taken over, and a
    customer that already pays for another tenant is not moved onto this one.
    """
    stored = await session.get(Customer, snapshot.tenant_id)
    if stored is not None and stored.provider_customer_id != snapshot.customer_id:
        raise SyncError("customer_mismatch", f"tenant {snapshot.tenant_id}")
    stmt = select(Customer.tenant_id).where(Customer.provider_customer_id == snapshot.customer_id)
    owner = (await session.execute(stmt)).scalar_one_or_none()
    if owner is not None and owner != snapshot.tenant_id:
        raise SyncError("customer_mismatch", f"customer of tenant {owner}")


async def process_webhook(
    app: FastAPI, provider: BillingProvider, body: bytes, headers: Mapping[str, str]
) -> tuple[int, str]:
    """Handle one delivery; returns ``(http_status, detail)``."""
    try:
        event = provider.parse_webhook(body, headers)
    except InvalidWebhookSignature:
        return 400, "invalid_signature"
    except ProviderError as exc:
        return 400, str(exc)

    try:
        if not await _claim(app, event, provider.name):
            return 200, "duplicate"
    except ProviderError as exc:
        return 500, str(exc)

    # A completed Checkout is gated on its session id: whether it made a
    # subscription is read from the re-fetched session, not the payload.
    checkout = event.type == CHECKOUT_COMPLETED
    target = (event.checkout_id or event.subscription_id) if checkout else event.subscription_id
    if event.type not in HANDLED_EVENTS or not target:
        await _finish(app, event.id, None)
        return 200, "ignored"

    try:
        snapshot, referenced = await _snapshot(provider, event)
        async with app.state.sm.db.session_factory() as session:
            if referenced:
                await _check_reference(session, snapshot)
            sub = await apply_snapshot(session, app, snapshot, provider=provider.name)
            tenant_id = sub.tenant_id
            await finalize_session(session)
    except SyncError as exc:
        if exc.code not in _ACKNOWLEDGED:
            return await _failed(app, event, exc)
        # Not ours (another product on the same Stripe account, or a tenant
        # since deleted), a Checkout naming a tenant someone else pays for,
        # or a lapse with nothing local to lapse; no retry
        # changes that. Acknowledge it, keep the reason: a permanent 500
        # would get the endpoint disabled for all.
        logger.warning("billing: webhook %s: %s — acknowledged", event.id, exc)
        await _finish(app, event.id, None, note=f"SyncError: {exc}")
        return 200, _ACKNOWLEDGED[exc.code]
    except Exception as exc:
        return await _failed(app, event, exc)
    await _finish(app, event.id, None)
    try:
        # Members may have changed between opening Checkout and paying it.
        await push_quantity(app, tenant_id)
    except Exception:
        logger.warning("billing: seat push after webhook %s failed", event.id, exc_info=True)
    return 200, "processed"


async def _failed(app: FastAPI, event: WebhookEvent, exc: Exception) -> tuple[int, str]:
    logger.error("billing: webhook %s (%s) failed: %s", event.id, event.type, exc, exc_info=exc)
    await _finish(app, event.id, f"{type(exc).__name__}: {exc}"[:2000])
    return 500, "processing_failed"
