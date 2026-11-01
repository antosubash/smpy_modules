"""The user-mode half of the deleted-subject sweep (#274).

The ``UserDeleted`` event fires once, so a cancel that failed is retried here:
``user:<id>`` customers whose ``users_user`` row is gone (users are
hard-deleted), whose teardown has not completed and whose retry is due. One
anti-join on ``users_user``, as :func:`sm_billing.sweep._orphans` does for
tenants, with the join key ``admin_users.user_rows`` uses.
:func:`sm_billing.sweep.run_teardown` runs each, with its claim and backoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, cast, literal, or_, select
from users.models import User

from sm_billing.constants import USER_SUBJECT_PREFIX
from sm_billing.models import Customer
from sm_billing.subjects import user_uuid

if TYPE_CHECKING:
    from fastapi import FastAPI


async def orphan_users(app: FastAPI, subject: str | None, now: datetime) -> list[str]:
    """Due, un-torn-down user customers whose user is gone."""
    key = literal(USER_SUBJECT_PREFIX, String).concat(cast(User.id, String))
    stmt = (
        select(Customer.tenant_id)
        .outerjoin(User, key == Customer.tenant_id)
        .where(
            User.id.is_(None),
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
    async with app.state.sm.db.session_factory() as session:
        candidates = (await session.scalars(stmt)).all()
    # A non-canonical spelling never matches the join, yet names no user that
    # was deleted either: never tear one down.
    return [candidate for candidate in candidates if user_uuid(candidate) is not None]
