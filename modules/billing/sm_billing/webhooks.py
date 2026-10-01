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
from sqlalchemy.exc import IntegrityError

from sm_billing.constants import HANDLED_EVENTS
from sm_billing.contracts.provider import InvalidWebhookSignature, ProviderError
from sm_billing.models import WebhookEvent as EventRow
from sm_billing.seats import push_quantity
from sm_billing.sync import SyncError, apply_snapshot

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.contracts.provider import BillingProvider, WebhookEvent

logger = logging.getLogger(__name__)


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

    if event.type not in HANDLED_EVENTS or not event.subscription_id:
        await _finish(app, event.id, None)
        return 200, "ignored"

    try:
        snapshot = await provider.fetch_subscription(event.subscription_id)
        if snapshot.tenant_id is None and event.tenant_id is not None:
            # checkout.session.completed carries client_reference_id even
            # when the subscription's own metadata is missing.
            snapshot = replace(snapshot, tenant_id=event.tenant_id)
        async with app.state.sm.db.session_factory() as session:
            sub = await apply_snapshot(session, app, snapshot, provider=provider.name)
            tenant_id = sub.tenant_id
            await finalize_session(session)
    except SyncError as exc:
        if exc.code != "unknown_tenant":
            return await _failed(app, event, exc)
        # Not ours (another product on the same Stripe account, or a tenant
        # since deleted) and no retry will make it ours. Acknowledge it, keep
        # the reason: a permanent 500 would get the endpoint disabled for all.
        logger.warning("billing: webhook %s: %s — acknowledged", event.id, exc)
        await _finish(app, event.id, None, note=f"SyncError: {exc}")
        return 200, "ignored_unknown_tenant"
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
