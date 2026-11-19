"""Adding, editing, pausing, refreshing and deleting a calendar's subscriptions.

Nothing here commits (the request's session does) and nothing fetches: a save makes the
subscription due, and the caller hands it to :mod:`~sm_events.feeds.subscriptions.launch`.

``may_use_private`` is set only here, only from ``policy.flag_after_save`` with the saver's
``events.manage``, never from a request body: a new or changed address takes the saver's right,
any other edit leaves it. The URL is sealed at once and shown only as ``url_display``.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from simple_module_db import mark_written
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from sm_events.core import constants
from sm_events.core.errors import Conflict, PublishRequired, Stale
from sm_events.core.errors_subscriptions import (
    RefreshTooSoon,
    SubscriptionExists,
    SubscriptionLimit,
    SubscriptionNotPublicCalendar,
)
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import policy, schedule, urls, validate
from sm_events.models import Calendar, ExternalItem, Subscription, Visibility
from sm_events.web.schemas.subscriptions import SubscriptionIn, SubscriptionOut, SubscriptionPatch

__all__ = ["create", "delete", "list_for", "pause", "refresh_now", "resume", "to_out", "update"]


class Context:
    """What a save needs beyond the principal: settings, the saver's rights and this site's own
    host names (for the own-feed refusal)."""

    def __init__(
        self,
        settings: EventsSettings,
        *,
        is_manager: bool,
        can_publish: bool,
        own_hosts: Collection[str] = (),
        public_prefix: str = "",
    ) -> None:
        self.settings, self.is_manager, self.can_publish = settings, is_manager, can_publish
        self.own_hosts, self.public_prefix = own_hosts, public_prefix


def _check_public(public: bool, calendar: Calendar, ctx: Context) -> None:
    if not public:
        return
    if not ctx.can_publish:
        raise PublishRequired
    if calendar.visibility != Visibility.PUBLIC.value:
        raise SubscriptionNotPublicCalendar


async def _live(db: Any, calendar_id: uuid.UUID) -> list[Subscription]:
    stmt = select(Subscription).where(Subscription.calendar_id == calendar_id)  # type: ignore[arg-type]
    return list((await db.execute(stmt.order_by(Subscription.label, Subscription.id))).scalars())  # type: ignore[arg-type]


def _same_address(held: list[Subscription], url: str, *, skip: uuid.UUID | None = None) -> bool:
    for sub in held:
        if sub.id == skip:
            continue
        try:
            if urls.unseal(sub.url_enc) == url:
                return True
        except urls.UrlUnreadable:
            continue  # an unreadable one cannot be compared: it never blocks a new address
    return False


def _make_due(sub: Subscription, now: datetime) -> None:
    sub.status, sub.error_code, sub.last_http_status = "pending", None, None
    sub.consecutive_failures, sub.next_fetch_at = 0, now
    sub.lease_owner = sub.lease_until = None


async def create(
    db: Any,
    who: ResourcePrincipal,
    calendar_id: uuid.UUID,
    body: SubscriptionIn,
    ctx: Context,
    *,
    now: datetime,
) -> Subscription:
    calendar = await validate.require_subscription_right(db, who, calendar_id, lock=True)
    _check_public(body.public, calendar, ctx)
    url, display = validate.check_url_for_save(
        body.url,
        settings=ctx.settings,
        is_manager=ctx.is_manager,
        own_hosts=ctx.own_hosts,
        public_prefix=ctx.public_prefix,
    )
    held = await _live(db, calendar.id)
    if len(held) >= constants.SUBSCRIPTIONS_PER_CALENDAR:
        raise SubscriptionLimit
    total = (
        await db.execute(
            select(func.count())
            .select_from(Subscription.__table__)
            .where(
                Subscription.__table__.c.tenant_id == bound_tenant(),
                Subscription.__table__.c.is_deleted.is_(False),
            )
        )
    ).scalar_one()
    if total >= constants.SUBSCRIPTIONS_PER_TENANT:
        raise SubscriptionLimit
    if _same_address(held, url):
        raise SubscriptionExists
    sub = Subscription(
        calendar_id=calendar.id,
        created_by=who.user_id or "",
        url_enc=urls.seal(url),
        url_display=display,
        label=body.label,
        color=body.color,
        refresh_minutes=body.refresh_minutes,
        public=body.public,
        may_use_private=policy.flag_after_save(
            False, url_changed=True, saver_may_use_private=ctx.is_manager
        ),
        created_at=now,
        updated_at=now,
    )
    _make_due(sub, now)
    db.add(sub)
    await db.flush()
    return sub


async def update(
    db: Any,
    who: ResourcePrincipal,
    sub_id: uuid.UUID,
    body: SubscriptionPatch,
    ctx: Context,
    *,
    now: datetime,
) -> Subscription:
    sub, calendar = await validate.load_subscription(db, who, sub_id, lock=True)
    if body.expected is not None and body.expected != sub.updated_at.isoformat():
        raise Stale
    sent = body.model_fields_set
    if "public" in sent and body.public is not None:
        _check_public(body.public, calendar, ctx)
        sub.public = body.public
    if body.label is not None:
        sub.label = body.label
    for field in ("color", "refresh_minutes"):
        if field in sent:
            setattr(sub, field, getattr(body, field))
    if body.url is not None:
        url, display = validate.check_url_for_save(
            body.url,
            settings=ctx.settings,
            is_manager=ctx.is_manager,
            own_hosts=ctx.own_hosts,
            public_prefix=ctx.public_prefix,
        )
        held = await _live(db, calendar.id)
        if _same_address(held, url, skip=sub.id):
            raise SubscriptionExists
        if not _same_address([sub], url):  # a changed address, not the one it already has
            sub.url_enc, sub.url_display = urls.seal(url), display
            sub.etag = sub.last_modified = None
            sub.may_use_private = policy.flag_after_save(
                sub.may_use_private, url_changed=True, saver_may_use_private=ctx.is_manager
            )
            _make_due(sub, now)
    sub.updated_at = now
    await db.flush()
    return sub


async def pause(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime
) -> Subscription:
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    sub.status, sub.updated_at = "paused", now
    sub.lease_owner = sub.lease_until = None
    await db.flush()
    return sub


async def resume(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime
) -> Subscription:
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    _make_due(sub, now)
    sub.updated_at = now
    await db.flush()
    return sub


async def refresh_now(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime
) -> Subscription:
    """Make it due now (a disabled one is resumed: this is the manual refresh it waits for).
    Refused while paused, within ``SUBSCRIPTION_REFRESH_NOW_SECONDS`` of its last fetch, and
    while someone holds its lease."""
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    if sub.status == "paused":
        raise Conflict(
            constants.SUBSCRIPTION_STATE_CONFLICT_DETAIL, constants.SUBSCRIPTION_STATE_CONFLICT_CODE
        )
    floor = timedelta(seconds=constants.SUBSCRIPTION_REFRESH_NOW_SECONDS)
    waits = []
    if sub.last_fetched_at is not None:
        waits.append(sub.last_fetched_at + floor - now)
    if sub.lease_until is not None and sub.lease_until > now:
        waits.append(sub.lease_until - now)
    wait = max(waits, default=timedelta(0))
    if wait > timedelta(0):
        raise RefreshTooSoon(retry_after=int(wait.total_seconds()) + 1)
    if sub.status in ("disabled", "error"):
        sub.consecutive_failures, sub.error_code = 0, None
    sub.status, sub.next_fetch_at, sub.updated_at = "pending", now, now
    await db.flush()
    return sub


async def delete(db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime) -> None:
    """Final: the row is soft-deleted with its address overwritten (no secret survives) and its
    items are removed in the same transaction. There is no restore."""
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    items = ExternalItem.__table__
    await db.execute(
        sa_delete(items).where(
            items.c.tenant_id == bound_tenant(), items.c.subscription_id == sub.id
        )
    )
    mark_written(db)  # Core DML: the ORM never sees it
    sub.url_enc, sub.is_deleted, sub.deleted_at = "", True, now
    sub.item_count, sub.lease_owner, sub.lease_until = 0, None, None
    sub.updated_at = now
    await db.flush()


async def list_for(db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID) -> list[Subscription]:
    await validate.require_subscription_right(db, who, calendar_id)
    return await _live(db, calendar_id)


def to_out(sub: Subscription, *, setting_minutes: int) -> SubscriptionOut:
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
        error_code=sub.error_code,
        last_http_status=sub.last_http_status,
        last_fetched_at=sub.last_fetched_at,
        last_ok_at=sub.last_ok_at,
        next_fetch_at=sub.next_fetch_at,
        consecutive_failures=sub.consecutive_failures,
        item_count=sub.item_count,
        last_counts=sub.last_counts,
        uses_internal_addresses=sub.may_use_private,
        version=sub.updated_at.isoformat(),
    )
