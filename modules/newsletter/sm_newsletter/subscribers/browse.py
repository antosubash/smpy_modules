"""The subscriber browse and detail, through the records contract (PR 6, Task 8).

Records owns the subscribers; this module narrows to a list the caller may read,
combines a tag and a segment (AND) into records filter terms, flags who is
suppressed here, and adds the newsletter side of one person: engagement
aggregates and the suppression rows that apply to their address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    SubscriberHit,
    subscribers_by_uuid,
)
from sm_records.contracts.newsletter_admin import (
    browse_subscribers,
    subscriber_admin_url,
    subscriber_status_counts,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles, require_list
from sm_newsletter.campaigns.audience import audience_filters
from sm_newsletter.core import constants
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidSegment
from sm_newsletter.core.suppression import normalise_email, suppressed
from sm_newsletter.subscribers.engagement import Engagement, engagement
from sm_newsletter.subscribers.lift import subscriber_on_list
from sm_newsletter.subscribers.suppressions import SuppressionRow, lift_block, rows_for_email

__all__ = [
    "BrowseResult",
    "SubscriberDetail",
    "SubscriberRow",
    "browse",
    "detail",
    "is_stopped",
    "stopped_among",
]


@dataclass(frozen=True)
class SubscriberRow:
    hit: SubscriberHit
    suppressed: bool


@dataclass(frozen=True)
class BrowseResult:
    rows: list[SubscriberRow]
    total: int
    counts: dict[str, int]


@dataclass(frozen=True)
class SubscriberDetail:
    hit: SubscriberHit
    engagement: Engagement
    suppressions: list[tuple[SuppressionRow, str | None]]
    suppressed: bool
    """Tenant-wide, as sending reads it: not narrowed by what the caller may see."""
    records_url: str


async def _filters(
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    tag: str | None,
    segment_id: int | None,
    roles: Roles,
) -> list[str]:
    out: list[str] = []
    for audience in (
        f"tag:{tag}" if tag is not None else None,
        f"segment:{segment_id}" if segment_id is not None else None,
    ):
        if audience is not None:
            out += await audience_filters(
                session,
                tenant_id=tenant_id,
                list_type_key=list_type_key,
                audience=audience,
                roles=roles,
            )
    return out


def is_stopped(email: str, stopped: set[str]) -> bool:
    """Whether ``email`` (any spelling) is in ``stopped``, the normalised suppressed set."""
    try:
        return normalise_email(email) in stopped
    except ValueError:
        return False


def _normalises(email: str) -> bool:
    try:
        normalise_email(email)
    except ValueError:
        return False
    return True


async def stopped_among(session: AsyncSession, *, tenant_id: str, emails: list[str]) -> set[str]:
    """``suppressed`` over the addresses that are addresses at all: a record with a
    blank ``sm_email`` is never suppressed (``is_stopped``), and must not make
    ``suppressed`` raise for the whole page."""
    usable = [e for e in emails if _normalises(e)]
    return await suppressed(session, tenant_id=tenant_id, emails=usable) if usable else set()


async def browse(
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    roles: Roles,
    status: str | None,
    q: str | None,
    tag: str | None,
    segment_id: int | None,
    offset: int,
    limit: int,
) -> BrowseResult:
    await require_list(session, tenant_id=tenant_id, list_type_key=list_type_key, roles=roles)
    filters = await _filters(
        session,
        tenant_id=tenant_id,
        list_type_key=list_type_key,
        tag=tag,
        segment_id=segment_id,
        roles=roles,
    )
    try:
        page = await browse_subscribers(
            session,
            tenant_id=tenant_id,
            type_key=list_type_key,
            filters=filters,
            status=status,  # type: ignore[arg-type]
            search=q,
            offset=offset,
            limit=limit,
        )
        counts = await subscriber_status_counts(
            session, tenant_id=tenant_id, type_key=list_type_key, filters=filters, search=q
        )
    except SubscriberFilterError:
        raise InvalidSegment("filter: refused") from None
    # Tenant-wide on purpose (TL1): a boolean only, no row detail; see subscribers/suppressions.py.
    stopped = await stopped_among(
        session, tenant_id=tenant_id, emails=[h.email for h in page.items]
    )
    rows = [SubscriberRow(hit=h, suppressed=is_stopped(h.email, stopped)) for h in page.items]
    return BrowseResult(rows=rows, total=page.total, counts=counts)


async def _confirmed_at(
    session: AsyncSession, *, tenant_id: str, row: SuppressionRow, hit: SubscriberHit, key: str
) -> datetime | None:
    """Display-only: when this address's confirmed subscription began, for an
    opt-out row (the lift re-checks under its own lock)."""
    if row.reason != constants.REASON_UNSUBSCRIBED or not row.list_type_key:
        return None
    if row.list_type_key == key:
        found = hit if hit.status == "confirmed" and not hit.trashed else None
    else:
        found = await subscriber_on_list(
            session, tenant_id=tenant_id, list_type_key=row.list_type_key, email=hit.email
        )
    return found.confirmed_at if found is not None else None


async def detail(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, uuid: str, roles: Roles
) -> SubscriberDetail:
    await require_list(session, tenant_id=tenant_id, list_type_key=list_type_key, roles=roles)
    found = await subscribers_by_uuid(
        session, tenant_id=tenant_id, type_key=list_type_key, uuids=[uuid]
    )
    hit = found.get(uuid)
    if hit is None:
        raise NotFound()
    rows = await rows_for_email(session, tenant_id=tenant_id, roles=roles, email=hit.email)
    suppressions = []
    for row in rows:
        at = await _confirmed_at(session, tenant_id=tenant_id, row=row, hit=hit, key=list_type_key)
        suppressions.append((row, lift_block(row, confirmed_at=at)))
    return SubscriberDetail(
        hit=hit,
        engagement=await engagement(session, tenant_id=tenant_id, record_uuid=uuid),
        suppressions=suppressions,
        suppressed=is_stopped(
            hit.email, await stopped_among(session, tenant_id=tenant_id, emails=[hit.email])
        ),
        records_url=subscriber_admin_url(list_type_key, uuid),
    )
