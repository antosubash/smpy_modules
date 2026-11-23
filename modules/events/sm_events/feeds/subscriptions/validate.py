"""What a save may carry: the address, and who may act on which calendar's subscriptions.

**The address is judged here without any lookup.** Syntax, scheme, credentials, port, a literal IP
and this site's own feed routes are checked; the name is resolved only by the worker, which
reports the outcome as the subscription's status. A save therefore answers a private literal and
an unresolvable name alike and in the same time, and cannot be used to ask the server's resolver
which internal names exist.

**The right** is the calendar's visibility right (the owner's, or ``events.manage``), the same one
that guards a calendar's sources: a subscription changes what the calendar's audience sees, and
its address is a credential only the owner should handle. A calendar the caller cannot see, and a
subscription on one, are ``NotFound``.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any
from urllib.parse import urlsplit

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.access import visible_calendars
from sm_events.core.access.rights import calendar_rights
from sm_events.core.errors import Forbidden, NotFound
from sm_events.core.errors_subscriptions import UrlRefused
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.feeds.subscriptions import policy, urls
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError
from sm_events.models import Calendar, Subscription

__all__ = ["check_url_for_save", "load_subscription", "require_subscription_right"]

OWN_FEED_CODE = "url_own_feed"


def _is_own_feed(url: str, own_hosts: Collection[str], public_prefix: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return host in {h.lower() for h in own_hosts} and (
        parts.path.startswith(public_prefix) or f"/{constants.FEED_PATH_SEGMENT}/" in parts.path
    )


def check_url_for_save(
    raw: str,
    *,
    settings: EventsSettings,
    is_manager: bool,
    own_hosts: Collection[str] = (),
    public_prefix: str = "",
) -> tuple[str, str]:
    """``(normalised address, masked form)``, or :class:`UrlRefused` with one code of the closed
    set. No lookup; see the module docstring."""
    try:
        url = policy.normalise(raw)
        policy.check(
            url,
            policy.effective(settings.allow_private_subscription_urls, may_use_private=is_manager),
        )
    except UnsafeURLError as error:
        raise UrlRefused(policy.user_code(error)) from None
    if _is_own_feed(url, own_hosts, public_prefix):
        raise UrlRefused(OWN_FEED_CODE)
    return url, urls.display_of(url)


async def require_subscription_right(
    db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID, *, lock: bool = False
) -> Calendar:
    """The calendar, when ``who`` may see it (``NotFound`` otherwise) **and** hold the
    subscription right (``Forbidden`` otherwise). ``lock`` takes its row, so two creates count
    its subscriptions one after the other."""
    if who.user_id is None or not who.has(constants.PERM_VIEW):
        raise NotFound
    stmt = visible_calendars(who).where(
        Calendar.id == calendar_id,  # type: ignore[arg-type]
        Calendar.tenant_id == bound_tenant(),  # type: ignore[arg-type]
    )
    if lock:
        stmt = stmt.with_for_update()
    calendar = (await db.execute(stmt)).scalar_one_or_none()
    if calendar is None:
        raise NotFound
    if not (await calendar_rights(db, who, calendar)).own:
        raise Forbidden
    return calendar


async def load_subscription(
    db: Any, who: ResourcePrincipal, sub_id: uuid.UUID, *, lock: bool = False
) -> tuple[Subscription, Calendar]:
    """The live subscription and its calendar, with the same answers as above. A foreign, deleted
    or invisible one is the same ``NotFound`` as an id that never existed."""
    stmt = select(Subscription).where(
        Subscription.id == sub_id,  # type: ignore[arg-type]
        Subscription.tenant_id == bound_tenant(),  # type: ignore[arg-type]
    )
    if lock:
        stmt = stmt.with_for_update()
    sub = (await db.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise NotFound
    calendar = await require_subscription_right(db, who, sub.calendar_id)
    return sub, calendar
