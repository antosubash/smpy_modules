"""Adding, editing, pausing, refreshing and deleting a calendar's subscriptions.

Nothing here commits (the request's session does) and nothing fetches: a save makes the
subscription due, and the caller hands it to :mod:`~sm_events.feeds.subscriptions.launch`.

``may_use_private`` is set only here, only from ``policy.flag_after_save`` with the saver's
``events.manage``, never from a request body: a new or changed address takes the saver's right,
any other edit leaves it. The URL is sealed at once and shown only as ``url_display``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from simple_module_db import mark_written
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from sm_events.core import constants
from sm_events.core.errors import Conflict, Stale
from sm_events.core.errors_subscriptions import (
    RefreshTooSoon,
    SubscriptionExists,
    SubscriptionLimit,
    SubscriptionPublishRequired,
)
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import generation, policy, rules, urls, validate
from sm_events.models import ExternalItem, Subscription
from sm_events.web.schemas.subscriptions import SubscriptionIn, SubscriptionPatch

__all__ = [
    "create",
    "delete",
    "list_for",
    "pause",
    "refresh_now",
    "resume",
    "update",
]


async def create(
    db: Any,
    who: ResourcePrincipal,
    calendar_id: uuid.UUID,
    body: SubscriptionIn,
    ctx: rules.Context,
    *,
    now: datetime,
) -> Subscription:
    calendar = await validate.require_subscription_right(db, who, calendar_id, lock=True)
    rules.check_public(body.public, calendar, ctx)
    internal_ok = ctx.is_manager and not body.public  # a public subscription is never internal
    flag_ok = (
        internal_ok and ctx.settings.allow_private_subscription_urls
    )  # and only with the switch
    url, display = validate.check_url_for_save(
        body.url,
        settings=ctx.settings,
        is_manager=internal_ok,
        own_hosts=ctx.own_hosts,
        public_prefix=ctx.public_prefix,
    )
    held = await rules.live(db, calendar.id)
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
    mine = (
        await db.execute(
            select(func.count())
            .select_from(Subscription.__table__)
            .where(
                Subscription.__table__.c.tenant_id == bound_tenant(),
                Subscription.__table__.c.is_deleted.is_(False),
                Subscription.__table__.c.created_by == (who.user_id or ""),
            )
        )
    ).scalar_one()
    if mine >= constants.SUBSCRIPTIONS_PER_OWNER:  # one member cannot take the whole allowance
        raise SubscriptionLimit
    if rules.same_address(held, url):
        raise SubscriptionExists
    sub = Subscription(
        calendar_id=calendar.id,
        created_by=who.user_id or "",
        url_enc=urls.seal(url),
        url_display=display,
        url_host=urls.host_of(url),
        label=body.label,
        color=body.color,
        refresh_minutes=body.refresh_minutes,
        public=body.public,
        may_use_private=policy.flag_after_save(
            False, url_changed=True, saver_may_use_private=flag_ok
        ),
        created_at=now,
        updated_at=now,
    )
    rules.make_due(sub, now)
    db.add(sub)
    await db.flush()
    return sub


async def update(
    db: Any,
    who: ResourcePrincipal,
    sub_id: uuid.UUID,
    body: SubscriptionPatch,
    ctx: rules.Context,
    *,
    now: datetime,
) -> Subscription:
    sub, calendar = await validate.load_subscription(db, who, sub_id, lock=True)
    if body.expected is not None and body.expected != sub.updated_at.isoformat():
        raise Stale
    sent = body.model_fields_set
    public = sub.public if body.public is None else body.public
    changes_shown = (
        (body.public is not None and body.public != sub.public)
        or body.url is not None
        or (body.label is not None and body.label != sub.label)
    )
    if (sub.public or public) and changes_shown and not ctx.can_publish:
        # What the public sees is chosen with the publish right, every time, in both directions
        # (like the workflow's approve and unpublish).
        raise SubscriptionPublishRequired
    moved = body.public is not None and body.public != sub.public
    flag_before = sub.may_use_private
    if public and body.public is not None and not sub.public:
        rules.check_public(True, calendar, ctx)
        rules.recheck_public(sub, ctx)  # an address needing internal access cannot be public
        sub.may_use_private = False
    sub.public = public
    if body.label is not None:
        sub.label = body.label
    for field in ("color", "refresh_minutes"):
        if field in sent:
            setattr(sub, field, getattr(body, field))
    if body.url is not None:
        url, display = validate.check_url_for_save(
            body.url,
            settings=ctx.settings,
            is_manager=ctx.is_manager and not public,
            own_hosts=ctx.own_hosts,
            public_prefix=ctx.public_prefix,
        )
        held = await rules.live(db, calendar.id)
        if rules.same_address(held, url, skip=sub.id):
            raise SubscriptionExists
        if not rules.same_address([sub], url):  # a changed address, not the one it already has
            sub.url_enc, sub.url_display = urls.seal(url), display
            sub.url_host = urls.host_of(url)
            moved = True
        # Any save that carries an address re-decides the flag from the saver and the switch now:
        # a subscription saved while the switch was off is not internal-capable until a manager
        # saves its address again with the switch on, and a non-manager's save clears it.
        sub.may_use_private = policy.flag_after_save(
            sub.may_use_private,
            url_changed=True,
            saver_may_use_private=ctx.is_manager
            and not public
            and ctx.settings.allow_private_subscription_urls,
        )
    if moved or sub.may_use_private != flag_before:
        await generation.restart(db, sub, now)  # the one place items and generation move
    sub.updated_at = now
    await db.flush()
    return sub


async def pause(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime
) -> Subscription:
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    sub.status, sub.updated_at = "paused", now
    await db.flush()
    return sub


async def resume(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, now: datetime
) -> Subscription:
    """Only from a pause or a stop, and only once. It always succeeds (a pause made by mistake is
    undone at once); the fetch itself waits for ``fetch_wait`` through ``next_fetch_at``."""
    sub, _ = await validate.load_subscription(db, who, sub_id, lock=True)
    if sub.status not in ("paused", "disabled"):
        raise Conflict(
            constants.SUBSCRIPTION_NOT_PAUSED_DETAIL, constants.SUBSCRIPTION_NOT_PAUSED_CODE
        )
    rules.make_due(sub, now)  # due after the floor, never earlier: no extra fetch is possible
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
    wait = rules.fetch_wait(sub, now)
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
    return await rules.live(db, calendar_id)
