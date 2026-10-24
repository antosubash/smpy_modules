"""Who may run a deleted tenant's teardown now, and what its outcome records (#92).

Every run (the ``TenantDeleted`` handler, ``reconcile_one``, the sweep, on any
number of workers) first *claims* the tenant's ``billing_customer`` row with one
conditional ``UPDATE`` on ``teardown_next_attempt_at``:

    SET teardown_next_attempt_at = <now + LEASE>
    WHERE tenant_id = :t AND (teardown_next_attempt_at IS NULL
                              OR teardown_next_attempt_at <= <now>)

Exactly one concurrent caller matches the row; only it calls the provider. The
claim value it wrote is its token: every outcome write is conditional on
``teardown_next_attempt_at`` still equalling it, so a run whose lease ran out
(and was claimed by another) writes nothing. A run that dies holding a claim
leaves a lease that expires after :data:`LEASE`, and the next tick claims it.
This is the scheduler's ``synced_at`` claim, on the customer row.

- **Success** clears the backoff (``teardown_attempts = 0``, next due ``NULL``).
  The teardown itself stamps ``teardown_done_at`` when it finished everything.
- **Failure** counts an attempt and sets the next due time from
  :func:`retry_delay` — for a customer whose teardown is done as well: its
  later passes (the mirrored-subscription recheck) back off the same way.

A deleted tenant with a mirrored subscription but no ``billing_customer`` row
has nothing to claim on and runs unguarded. ``apply_snapshot`` links a customer
whenever the provider names one, which Stripe always does, so this is the
admin-imported edge case only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from simple_module_db import finalize_session
from sqlalchemy import or_, select, update

from sm_billing.models import Customer

if TYPE_CHECKING:
    from fastapi import FastAPI

#: How long a claim holds before another run may take the tenant over.
LEASE = timedelta(minutes=5)
#: First retry delay after a failed teardown; doubles per failure.
RETRY_BASE = timedelta(minutes=15)
#: Longest gap between two retries of one customer.
RETRY_CAP = timedelta(hours=24)

#: ``claim``'s answer when the tenant has no customer row to claim on.
UNGUARDED = datetime.min.replace(tzinfo=UTC)


def retry_delay(attempts: int) -> timedelta:
    """The wait after the ``attempts``-th consecutive failure."""
    exponent = min(max(0, attempts - 1), 16)  # 15 min * 2**7 already passes the cap
    return min(RETRY_BASE * 2**exponent, RETRY_CAP)


async def claim(app: FastAPI, tenant_id: str) -> datetime | None:
    """Claim the tenant's teardown; its token, ``None`` if not due or taken.

    :data:`UNGUARDED` when there is no customer row to claim on.
    """
    now = datetime.now(UTC)
    token = now + LEASE
    stmt = (
        update(Customer)
        .where(
            Customer.tenant_id == tenant_id,
            or_(
                Customer.teardown_next_attempt_at.is_(None),
                Customer.teardown_next_attempt_at <= now,
            ),
        )
        .values(teardown_next_attempt_at=token)
    )
    async with app.state.sm.db.session_factory() as session:
        won = (await session.execute(stmt)).rowcount == 1  # ty: ignore[unresolved-attribute]
        exists = won or await session.get(Customer, tenant_id) is not None
        await finalize_session(session)
    if won:
        return token
    return None if exists else UNGUARDED


async def succeeded(app: FastAPI, tenant_id: str, token: datetime) -> None:
    """Clear the backoff, if the claim is still ours."""
    if token is UNGUARDED:
        return
    stmt = (
        update(Customer)
        .where(Customer.tenant_id == tenant_id, Customer.teardown_next_attempt_at == token)
        .values(teardown_attempts=0, teardown_next_attempt_at=None)
    )
    async with app.state.sm.db.session_factory() as session:
        await session.execute(stmt)
        await finalize_session(session)


async def failed(app: FastAPI, tenant_id: str, token: datetime) -> None:
    """Count an attempt and set the next due time, if the claim is still ours."""
    if token is UNGUARDED:
        return
    async with app.state.sm.db.session_factory() as session:
        attempts = await session.scalar(
            select(Customer.teardown_attempts).where(
                Customer.tenant_id == tenant_id, Customer.teardown_next_attempt_at == token
            )
        )
        if attempts is not None:
            await session.execute(
                update(Customer)
                .where(
                    Customer.tenant_id == tenant_id,
                    Customer.teardown_next_attempt_at == token,
                    Customer.teardown_attempts == attempts,
                )
                .values(
                    teardown_attempts=attempts + 1,
                    teardown_next_attempt_at=datetime.now(UTC) + retry_delay(attempts + 1),
                )
            )
        await finalize_session(session)
