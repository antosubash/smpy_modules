"""The reconcile sweep over deleted tenants' leftovers (#92).

The retry path ``reconcile_one`` cannot reach: a customer with no mirrored
subscription (one not mirrored yet, or a local-only row) or an open checkout.
Every reconcile — ``smpy billing reconcile`` and the scheduled tick — ends with
it. It selects each ``billing_customer`` whose tenant is gone, whose teardown
has not completed (``teardown_done_at``) and whose retry is due
(``teardown_next_attempt_at``), and runs :mod:`sm_billing.teardown` for it.

- **Cheap once done.** A stamped customer is never selected again.
- **Claim and backoff.** :func:`run_teardown` is the only way a deleted
  tenant's teardown runs — this sweep, ``reconcile_one`` for a mirrored
  subscription, and the ``TenantDeleted`` handler — and it first wins an
  atomic claim on the customer row (:mod:`sm_billing.teardown_claim`), so two
  concurrent runs never both call the provider. A failure counts
  ``teardown_attempts`` up and puts the next try 15 minutes away, doubling to
  a day, for a torn-down customer's later rechecks too; success clears it. "Not found"
  at the provider is a failure like any other: it may be a key for another
  account or mode, so it is retried (warned about), never taken as done.
- **Failure budget.** Under the scheduler the sweep shares the tick's
  :class:`Budget`: provider errors double the pause and enough of them in a row
  end the tick, exactly as for subscriptions, so an outage is waited out.
- **Live settings.** Before each tenant it re-reads the stored provider
  (``live.ensure_current``) and stops when it changed — a switch to ``manual``
  on another worker stops the cancels here too.
- **Single-tenant hosts in tenant mode never sweep.** There everything is
  ``"default"`` with no tenant row, which would read as deleted; ``"default"``
  is never swept.
- **User mode sweeps users instead (#274).** There the sweep selects the
  ``user:<id>`` customers whose user is gone (the retry for a ``UserDeleted``
  cancel that failed, :mod:`sm_billing.user_teardown`) and nothing else. In
  tenant mode a ``user:<id>`` customer (one left over from switching
  ``subject_mode``) is no deleted tenant and is never swept.

Two instances sweeping one customer at once only cost calls: the teardown is
idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import or_, select
from tenants.models import Tenant

from sm_billing import live
from sm_billing.constants import SUBJECT_MODE_USER as USER_MODE
from sm_billing.constants import USER_SUBJECT_PREFIX
from sm_billing.contracts.provider import ProviderError, ProviderNotFound
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.models import Customer
from sm_billing.teardown import cancel_for_deleted_tenant
from sm_billing.subjects import subject_mode
from sm_billing.teardown_claim import claim, failed, succeeded
from sm_billing.user_sweep import orphan_users

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.reconcile import ReconcileReport

logger = logging.getLogger(__name__)


@dataclass
class Budget:
    """The scheduler's pacing and provider-error budget, carried into the sweep."""

    pause: Callable[[float], Awaitable[None]]
    base: float
    cap: float
    max_errors: int
    current: float
    errors: int = 0

    def succeeded(self) -> None:
        self.current, self.errors = self.base, 0

    def failed(self, exc: Exception) -> bool:
        """Count ``exc``; ``True`` when the run should stop."""
        if not isinstance(exc, ProviderError):
            return False
        self.errors += 1
        self.current = min(self.current * 2, self.cap)
        return self.errors >= self.max_errors


async def _orphans(app: FastAPI, tenant_id: str | None, now: datetime) -> list[str]:
    """Customers whose tenant is gone, not torn down, and due for a try."""
    stmt = (
        select(Customer.tenant_id)
        .outerjoin(Tenant, Tenant.id == Customer.tenant_id)
        .where(
            Tenant.id.is_(None),
            Customer.tenant_id != DEFAULT_TENANT_ID,
            Customer.tenant_id.not_like(f"{USER_SUBJECT_PREFIX}%"),
            Customer.provider_customer_id.is_not(None),
            Customer.teardown_done_at.is_(None),
            or_(
                Customer.teardown_next_attempt_at.is_(None),
                Customer.teardown_next_attempt_at <= now,
            ),
        )
        .order_by(Customer.teardown_next_attempt_at.asc().nulls_first(), Customer.tenant_id)
    )
    if tenant_id is not None:
        stmt = stmt.where(Customer.tenant_id == tenant_id)
    async with app.state.sm.db.session_factory() as session:
        return list((await session.scalars(stmt)).all())


async def run_teardown(app: FastAPI, tenant_id: str) -> list[str] | None:
    """The one way a deleted tenant's teardown runs: the ``TenantDeleted``
    handler, ``reconcile_one`` and the sweep all come through here.

    Returns ``None`` without a provider call unless this call wins the
    tenant's claim (:mod:`sm_billing.teardown_claim`: due, and no other run
    holding it), else what :func:`~sm_billing.teardown.cancel_for_deleted_tenant`
    canceled. Success clears the backoff; a failure is recorded (attempts, next
    due time) — for a customer already torn down too — logged and re-raised for
    the caller's report and budget.
    """
    token = await claim(app, tenant_id)
    if token is None:
        return None  # not due, or another run holds it right now
    try:
        canceled = await cancel_for_deleted_tenant(app, tenant_id)
    except Exception as exc:
        await failed(app, tenant_id, token)
        if isinstance(exc, ProviderNotFound):
            logger.warning(
                "billing: the provider has no record of deleted tenant %s's customer or "
                "subscription (%s). If the Stripe key is for another account or test/live "
                "mode, fix it; the teardown retries with backoff either way",
                tenant_id,
                exc,
            )
        else:
            logger.warning("billing: teardown failed for tenant %s", tenant_id, exc_info=True)
        raise
    await succeeded(app, tenant_id, token)
    return canceled


async def sweep_deleted_tenants(
    app: FastAPI,
    report: ReconcileReport,
    *,
    tenant_id: str | None = None,
    attempted: Collection[str] = (),
    budget: Budget | None = None,
) -> None:
    """Retry every due teardown; ``attempted`` were tried by this run already."""
    user_mode = subject_mode(app) == USER_MODE
    if not user_mode and not is_multi_tenant(app):
        return
    now = datetime.now(UTC)
    if user_mode:
        orphans = await orphan_users(app, tenant_id, now)
    else:
        orphans = await _orphans(app, tenant_id, now)
    for orphan in orphans:
        if orphan in attempted:
            continue
        if await live.ensure_current(app):
            report.skipped = "settings changed"  # the next run uses the new provider
            return
        try:
            if await run_teardown(app, orphan) is None:
                continue  # its retry was pushed back since the query
        except Exception as exc:
            report.errors.append((orphan, f"{type(exc).__name__}: {exc}"))
            if budget is not None and budget.failed(exc):
                report.skipped = "provider failing"
                logger.warning("billing: provider failing; the sweep resumes next interval")
                return
        else:
            report.torn_down += 1
            if budget is not None:
                budget.succeeded()
        if budget is not None:
            await budget.pause(budget.current)
