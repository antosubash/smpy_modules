"""What the API says about subscriptions: the shape of one and how much room is left (PR 10).

Split from :mod:`sm_events.feeds.subscriptions.service` (file size); read-only, nothing here
writes.
"""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import func, select

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import schedule, validate
from sm_events.models import Subscription
from sm_events.web.schemas.subscriptions import SubscriptionOut

__all__ = ["capacity", "to_out"]


async def capacity(
    db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID
) -> dict[str, dict[str, int]]:
    """How much room the calendar, the caller (as a member) and the tenant have left, the same
    counts ``create`` checks (``used`` and ``limit`` each)."""
    await validate.require_subscription_right(db, who, calendar_id)
    table = Subscription.__table__
    live = (table.c.tenant_id == bound_tenant(), table.c.is_deleted.is_(False))

    async def used(*extra: Any) -> int:
        stmt = select(func.count()).select_from(table).where(*live, *extra)
        return int((await db.execute(stmt)).scalar_one())

    return {
        "calendar": {
            "used": await used(table.c.calendar_id == calendar_id),
            "limit": constants.SUBSCRIPTIONS_PER_CALENDAR,
        },
        "owner": {
            "used": await used(table.c.created_by == (who.user_id or "")),
            "limit": constants.SUBSCRIPTIONS_PER_OWNER,
        },
        "tenant": {"used": await used(), "limit": constants.SUBSCRIPTIONS_PER_TENANT},
    }


def to_out(
    sub: Subscription, *, setting_minutes: int, is_manager: bool = False, internal_on: bool = False
) -> SubscriptionOut:
    """The API shape. That an address may be internal says an intranet service exists, so only
    ``events.manage`` holders are told, and only while the install switch is on (the effective
    policy, not the stored flag alone); everyone else gets ``False``."""
    internal = sub.may_use_private and internal_on and not sub.public
    hidden = internal and not is_manager  # a non-manager may not learn what failed
    shown_code = "url_unreachable" if hidden and sub.error_code else sub.error_code
    return SubscriptionOut(
        id=sub.id,
        calendar_id=sub.calendar_id,
        url_display=sub.url_display,
        label=sub.label,
        color=sub.color,
        refresh_minutes=sub.refresh_minutes,
        effective_refresh_minutes=schedule.effective_minutes(sub.refresh_minutes, setting_minutes),
        public=sub.public,
        status=sub.status,
        error_code=shown_code,
        last_http_status=None if hidden else sub.last_http_status,
        last_fetched_at=sub.last_fetched_at,
        last_ok_at=sub.last_ok_at,
        next_fetch_at=sub.next_fetch_at,
        consecutive_failures=sub.consecutive_failures,
        item_count=sub.item_count,
        last_counts=sub.last_counts,
        may_use_internal_addresses=internal and is_manager,
        version=sub.updated_at.isoformat(),
    )
