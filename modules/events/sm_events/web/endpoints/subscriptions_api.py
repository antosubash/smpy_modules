"""``/api/events``: a calendar's external subscriptions.

The parent router binds the tenant (first) and the CSRF check. Every route needs ``events.view``;
the right to subscribe is the calendar's visibility right (the owner's or ``events.manage``): a
calendar the caller cannot see, and a subscription on one, are the same 404 as an id that does not
exist. The address is accepted once and never returned: only ``url_display``.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.host_settings import public_base_url
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import launch, rules, service
from sm_events.web.endpoints.deps import Principal, get_settings, require_view
from sm_events.web.endpoints.public import _urls
from sm_events.web.schemas.subscriptions import SubscriptionIn, SubscriptionOut, SubscriptionPatch

router = APIRouter(tags=["subscriptions"], dependencies=[require_view])

_ID = "[^/]+"  # whatever spelling of a UUID the route accepts (hex, braces, urn:uuid:)
_CALENDAR_SUBS = rf"calendars/{_ID}/subscriptions"
_ONE = rf"subscriptions/{_ID}(?:/refresh|/resume)?"
PATH_PATTERN = rf"^{constants.ROUTE_PREFIX_API}/(?:{_CALENDAR_SUBS}|{_ONE})$"
"""Every route that can start a fetch: create, edit (a new address), refresh and resume."""
RATE = constants.SUBSCRIPTION_WRITE_RATE


def _context(request: Request, who, settings: EventsSettings) -> rules.Context:
    hosts = {request.url.hostname or ""}
    if base := public_base_url(request.app):
        hosts.add(urlsplit(base).hostname or "")
    return rules.Context(
        settings,
        is_manager=who.has(constants.PERM_MANAGE),
        can_publish=who.has(constants.PERM_PUBLISH),
        own_hosts={h for h in hosts if h},
        public_prefix=_urls.prefix(),
    )


def _out(sub, settings: EventsSettings, who) -> SubscriptionOut:
    return service.to_out(
        sub,
        setting_minutes=settings.subscription_refresh_minutes,
        is_manager=who.has(constants.PERM_MANAGE),
        internal_on=settings.allow_private_subscription_urls,
    )


def _start(request: Request, db, sub, settings: EventsSettings) -> bool:
    """Launch the fetch now. ``True`` when it is only queued: due later (a wait or a lease: the beat
    picks it up) or sent to a worker that takes it up when it can; ``False`` when it ran inline."""
    if sub.next_fetch_at is None or sub.next_fetch_at > utcnow():
        return True
    state = getattr(request.app.state, "sm", None)
    launch.refresh_one(
        db,
        tenant_id=bound_tenant(),
        subscription_id=sub.id,
        session_factory=getattr(getattr(state, "db", None), "session_factory", None),
        settings=settings,
    )
    return not launch.celery_eager()


@router.get("/calendars/{calendar_id}/subscriptions")
async def list_subscriptions(
    calendar_id: uuid.UUID,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> list[SubscriptionOut]:
    return [_out(s, settings, who) for s in await service.list_for(db, who, calendar_id)]


@router.get("/calendars/{calendar_id}/subscriptions/capacity")
async def subscription_capacity(
    calendar_id: uuid.UUID, who: Principal, db=Depends(get_db)
) -> dict[str, dict[str, int]]:
    return await service.capacity(db, who, calendar_id)


@router.post("/calendars/{calendar_id}/subscriptions", status_code=201)
async def create_subscription(
    calendar_id: uuid.UUID,
    body: SubscriptionIn,
    request: Request,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> SubscriptionOut:
    sub = await service.create(
        db, who, calendar_id, body, _context(request, who, settings), now=utcnow()
    )
    _start(request, db, sub, settings)
    return _out(sub, settings, who)


@router.patch("/subscriptions/{sub_id}")
async def update_subscription(
    sub_id: uuid.UUID,
    body: SubscriptionPatch,
    request: Request,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> SubscriptionOut:
    sub = await service.update(
        db, who, sub_id, body, _context(request, who, settings), now=utcnow()
    )
    if sub.status == "pending" and "url" in body.model_fields_set:
        _start(request, db, sub, settings)
    return _out(sub, settings, who)


@router.post("/subscriptions/{sub_id}/refresh", status_code=202)
async def refresh_subscription(
    sub_id: uuid.UUID,
    request: Request,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> SubscriptionOut:
    sub = await service.refresh_now(db, who, sub_id, now=utcnow())
    queued = _start(request, db, sub, settings)
    out = _out(sub, settings, who)
    if queued:  # say so: the fetch has not run yet and the screen would otherwise look unchanged
        out.queued, out.queued_minutes = True, constants.SUBSCRIPTION_QUEUED_MINUTES
    return out


@router.post("/subscriptions/{sub_id}/pause")
async def pause_subscription(
    sub_id: uuid.UUID,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> SubscriptionOut:
    return _out(await service.pause(db, who, sub_id, now=utcnow()), settings, who)


@router.post("/subscriptions/{sub_id}/resume")
async def resume_subscription(
    sub_id: uuid.UUID,
    request: Request,
    who: Principal,
    db=Depends(get_db),
    settings: EventsSettings = Depends(get_settings),
) -> SubscriptionOut:
    sub = await service.resume(db, who, sub_id, now=utcnow())
    _start(request, db, sub, settings)
    return _out(sub, settings, who)


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(sub_id: uuid.UUID, who: Principal, db=Depends(get_db)) -> Response:
    await service.delete(db, who, sub_id, now=utcnow())
    return Response(status_code=204)
