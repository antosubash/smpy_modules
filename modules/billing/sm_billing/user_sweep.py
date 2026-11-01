"""The user-mode half of the deleted-subject sweep (#274).

The ``UserDeleted`` event fires once, so a cancel that failed is retried here:
``user:<id>`` customers whose ``users_user`` row is gone (users are
hard-deleted), whose teardown has not completed and whose retry is due.
:func:`sm_billing.sweep.run_teardown` runs each, with its claim and backoff.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from users.models import User

from sm_billing.constants import USER_SUBJECT_PREFIX
from sm_billing.models import Customer

if TYPE_CHECKING:
    from fastapi import FastAPI


async def orphan_users(app: FastAPI, subject: str | None, now: datetime) -> list[str]:
    """Due, un-torn-down user customers whose user is gone."""
    stmt = (
        select(Customer.tenant_id)
        .where(
            Customer.tenant_id.like(f"{USER_SUBJECT_PREFIX}%"),
            Customer.provider_customer_id.is_not(None),
            Customer.teardown_done_at.is_(None),
            or_(
                Customer.teardown_next_attempt_at.is_(None),
                Customer.teardown_next_attempt_at <= now,
            ),
        )
        .order_by(Customer.teardown_next_attempt_at.asc().nulls_first(), Customer.tenant_id)
    )
    if subject is not None:
        stmt = stmt.where(Customer.tenant_id == subject)
    gone: list[str] = []
    async with app.state.sm.db.session_factory() as session:
        for candidate in (await session.scalars(stmt)).all():
            try:
                user_id = uuid.UUID(candidate[len(USER_SUBJECT_PREFIX) :])
            except ValueError:
                continue
            if await session.get(User, user_id) is None:
                gone.append(candidate)
    return gone
