"""What an admin does to one subscriber: tag, untag, unsubscribe (PR 6, Task 9).

Records owns the subscriber, so both writes go through its contract and run in
the caller's transaction; this module finishes it with ``finalize_session``
(never ``commit()``: ``RecordUpdated`` and ``SubscriptionChanged`` publish only
there). Lock order (ruling R4): records' rows first, then the suppression upsert.
The campaign and send rows are never touched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    SubscriberHit,
    SubscriberNotFound,
    ValidationFailed,
    set_tags,
    subscribers_by_uuid,
    unsubscribe,
)
from sm_records.contracts.newsletter_admin import list_fields
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles, require_list
from sm_newsletter.campaigns.audience import MAX_TAG_LEN
from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidQuery, NotSubscribed, UnknownTag
from sm_newsletter.core.suppression import suppress, suppressed
from sm_newsletter.subscribers.browse import SubscriberRow, is_stopped

__all__ = ["MAX_TAG_VALUES", "row_of", "set_subscriber_tags", "unsubscribe_subscriber"]

MAX_TAG_VALUES = 20


def _checked(values: list[str]) -> None:
    if len(values) > MAX_TAG_VALUES or any(
        not isinstance(v, str) or not v or len(v) > MAX_TAG_LEN for v in values
    ):
        raise InvalidQuery()


async def _choices(session: AsyncSession, tenant_id: str, list_type_key: str) -> set[str]:
    try:
        fields = await list_fields(session, tenant_id=tenant_id, type_key=list_type_key)
    except SubscriberFilterError:
        raise NotFound() from None
    tags = next((f for f in fields if f.key == constants.TAGS_FIELD and f.many), None)
    if tags is None:
        raise UnknownTag()
    return {c.value for c in tags.choices}


async def _read(session: AsyncSession, tenant_id: str, list_type_key: str, uuid: str):
    hits = await subscribers_by_uuid(
        session, tenant_id=tenant_id, type_key=list_type_key, uuids=[uuid]
    )
    hit = hits.get(uuid)
    if hit is None or hit.trashed:
        raise NotFound()
    return hit


async def row_of(session: AsyncSession, *, tenant_id: str, hit: SubscriberHit) -> SubscriberRow:
    """``hit`` with its tenant-wide suppressed flag, as the browse answers it."""
    stopped = await suppressed(session, tenant_id=tenant_id, emails=[hit.email])
    return SubscriberRow(hit=hit, suppressed=is_stopped(hit.email, stopped))


async def set_subscriber_tags(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    uuid: str,
    add: list[str],
    remove: list[str],
    roles: Roles,
) -> SubscriberHit:
    await require_list(session, tenant_id=tenant_id, list_type_key=list_type_key, roles=roles)
    _checked(add)
    _checked(remove)
    choices = await _choices(session, tenant_id, list_type_key)
    if not set(add) <= choices:
        raise UnknownTag()  # removing a value that is no longer a choice is allowed
    try:
        hit = await set_tags(
            session,
            tenant_id=tenant_id,
            type_key=list_type_key,
            uuid=uuid,
            add=add,
            remove=remove,
            settings=app.state.sm_records.settings,
            bus=app.state.sm.event_bus,
        )
    except (SubscriberNotFound, SubscriberFilterError):
        raise NotFound() from None
    except ValidationFailed:  # a choice removed since _choices read it
        raise UnknownTag() from None
    await finalize_session(session)
    return hit


async def unsubscribe_subscriber(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    uuid: str,
    roles: Roles,
    now: datetime,
) -> SubscriberHit:
    """Records' opt-out and the tenant-wide suppression, in one transaction (G14).
    :class:`NotSubscribed` when records wrote nothing for a live subscriber."""
    await require_list(session, tenant_id=tenant_id, list_type_key=list_type_key, roles=roles)
    try:
        wrote = await unsubscribe(
            session,
            tenant_id=tenant_id,
            type_key=list_type_key,
            uuid=uuid,
            unless_confirmed_after=None,
            settings=app.state.sm_records.settings,
            bus=app.state.sm.event_bus,
        )
    except SubscriberFilterError:
        raise NotFound() from None
    hit = await _read(session, tenant_id, list_type_key, uuid)
    if not wrote:
        raise NotSubscribed()
    await suppress(
        session,
        tenant_id=tenant_id,
        email=hit.email,
        reason=constants.REASON_UNSUBSCRIBED,
        source=constants.SOURCE_ADMIN,
        list_type_key=list_type_key,
        now=now,
    )
    await finalize_session(session)
    return hit
