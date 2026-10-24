"""The reconcile sweep over deleted tenants' leftovers (#92).

The retry path ``reconcile_one`` cannot reach: a customer with no mirrored
subscription (one not mirrored yet, or a local-only row) or an open checkout.
Every reconcile — ``smpy billing reconcile`` and the scheduled tick — ends with
it. It selects each ``billing_customer`` whose tenant is gone, whose teardown
has not completed (``teardown_done_at``) and whose retry is due
(``teardown_next_attempt_at``), and runs :mod:`sm_billing.teardown` for it.

- **Cheap once done.** A stamped customer is never selected again.
- **Backoff.** A failure counts ``teardown_attempts`` up and puts the next try
  ``RETRY_BASE * 2**(attempts-1)`` away, capped at ``RETRY_CAP``, so a customer
  that keeps failing is not retried on every tick. A customer the provider no
  longer has is terminal inside the teardown (stamped done), not a failure.
- **Failure budget.** Under the scheduler the sweep shares the tick's
  :class:`Budget`: provider errors double the pause and enough of them in a row
  end the tick, exactly as for subscriptions, so an outage is waited out.
- **Live settings.** Before each tenant it re-reads the stored provider
  (``live.ensure_current``) and stops when it changed — a switch to ``manual``
  on another worker stops the cancels here too.
- **Single-tenant hosts never sweep.** There everything is ``"default"`` with
  no tenant row, which would read as deleted; ``"default"`` is never swept.

Two instances sweeping one customer at once only cost calls: the teardown is
idempotent.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from simple_module_db import finalize_session
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from sqlalchemy import or_, select
from tenants.models import Tenant

from sm_billing import live
from sm_billing.contracts.provider import ProviderError
from sm_billing.lifecycle import is_multi_tenant
from sm_billing.models import Customer
from sm_billing.teardown import cancel_for_deleted_tenant

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sm_billing.reconcile import ReconcileReport

logger = logging.getLogger(__name__)

#: First retry delay after a failed teardown; doubles per failure.
RETRY_BASE = timedelta(minutes=15)
#: Longest gap between two retries of one customer.
RETRY_CAP = timedelta(hours=24)


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


def retry_delay(attempts: int) -> timedelta:
    """The wait after the ``attempts``-th consecutive failure."""
    exponent = min(max(0, attempts - 1), 16)  # 15 min * 2**7 already passes the cap
    return min(RETRY_BASE * 2**exponent, RETRY_CAP)


async def _orphans(app: FastAPI, tenant_id: str | None, now: datetime) -> list[str]:
    """Customers whose tenant is gone, not torn down, and due for a try."""
    stmt = (
        select(Customer.tenant_id)
        .outerjoin(Tenant, Tenant.id == Customer.tenant_id)
        .where(
            Tenant.id.is_(None),
            Customer.tenant_id != DEFAULT_TENANT_ID,
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


async def _back_off(app: FastAPI, tenant_id: str) -> None:
    async with app.state.sm.db.session_factory() as session:
        customer = await session.get(Customer, tenant_id)
        if customer is not None and customer.teardown_done_at is None:
            customer.teardown_attempts += 1
            delay = retry_delay(customer.teardown_attempts)
            customer.teardown_next_attempt_at = datetime.now(UTC) + delay
        await finalize_session(session)


async def sweep_deleted_tenants(
    app: FastAPI,
    report: ReconcileReport,
    *,
    tenant_id: str | None = None,
    attempted: Collection[str] = (),
    budget: Budget | None = None,
) -> None:
    """Retry every due teardown; ``attempted`` were tried by this run already."""
    if not is_multi_tenant(app):
        return
    for orphan in await _orphans(app, tenant_id, datetime.now(UTC)):
        if orphan in attempted:
            continue
        if await live.ensure_current(app):
            report.skipped = "settings changed"  # the next run uses the new provider
            return
        try:
            await cancel_for_deleted_tenant(app, orphan)
        except Exception as exc:
            logger.warning("billing: teardown retry failed for tenant %s", orphan, exc_info=True)
            report.errors.append((orphan, f"{type(exc).__name__}: {exc}"))
            await _back_off(app, orphan)
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
