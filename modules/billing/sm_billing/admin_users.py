"""The admin subscriptions list in ``subject_mode = "user"``, and its row shape.

In user mode the list is driven from ``users_user`` the way the tenant list is
driven from ``tenants_tenant``: every user, outer-joined to their subscription
(``tenant_id == "user:" || users_user.id``), in the same ``SubscriptionRow``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, cast, literal, select
from tenants.models import Tenant
from users.models import User

from sm_billing import constants as c
from sm_billing import subjects
from sm_billing.errors import BillingError
from sm_billing.models import Plan, Subscription
from sm_billing.schemas import SubscriptionRow

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession


def row(
    subject: str,
    name: str,
    slug: str,
    subject_status: str,
    members: int,
    sub: Subscription | None,
    shown: Plan,
) -> SubscriptionRow:
    """One row: ``shown`` is the subscribed plan even when lapsed, else the default."""
    return SubscriptionRow(
        tenant_id=subject,
        tenant_name=name,
        tenant_slug=slug,
        tenant_status=subject_status,
        members=members,
        plan_id=shown.id,
        plan_key=shown.key,
        plan_name=shown.name,
        status=sub.status if sub else None,
        interval=sub.interval if sub else None,
        quantity=sub.quantity if sub else None,
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=bool(sub and sub.cancel_at_period_end),
        suspended_by_billing=bool(sub and sub.suspended_by_billing),
        provider_subscription_id=sub.provider_subscription_id if sub else None,
        synced_at=sub.synced_at if sub else None,
    )


async def user_rows(
    db: AsyncSession,
    default: Plan,
    *,
    status: str | None,
    subject: str | None,
    limit: int,
    offset: int,
) -> list[SubscriptionRow]:
    # Built in SQL so paging and the status filter stay one query: the GUID
    # column is the dashed string on SQLite and a native uuid on Postgres, and
    # both cast to the dashed text ``subject_for_user`` writes.
    key = literal(c.USER_SUBJECT_PREFIX, String).concat(cast(User.id, String))
    stmt = (
        select(User.id, User.email, User.is_active, Subscription, Plan)
        .outerjoin(Subscription, Subscription.tenant_id == key)
        .outerjoin(Plan, Plan.id == Subscription.plan_id)
        .order_by(User.email, User.id)
        .limit(limit)
        .offset(offset)
    )
    if status:
        stmt = stmt.where(Subscription.status == status)
    if subject is not None:
        user_id = subjects.user_uuid(subject)
        if user_id is None:
            return []
        stmt = stmt.where(User.id == user_id)
    return [
        row(
            subjects.subject_for_user(user_id),
            email,
            "",
            "active" if is_active else "inactive",
            1,
            sub,
            plan if plan is not None else default,
        )
        for user_id, email, is_active, sub, plan in (await db.execute(stmt)).all()
    ]


async def require_subject(db: AsyncSession, app: FastAPI, subject: str) -> None:
    """404 ``tenant_not_found`` unless ``subject`` is a row of this mode's list.

    Tenant mode keeps its organisation check as it was (``"default"`` is no
    organisation); user mode takes an existing user's canonical subject only.
    Mode-strict on purpose: rows left from the other mode are repaired through
    the usage admin (``metering.admin.require_tenant``), not assigned here.
    """
    if subjects.subject_mode(app) == c.SUBJECT_MODE_USER:
        found = subjects.kind(subject) == c.SUBJECT_MODE_USER and await subjects.exists(db, subject)
    else:
        found = await db.get(Tenant, subject) is not None
    if not found:
        raise BillingError("tenant_not_found", 404)
