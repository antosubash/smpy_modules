"""Who in the list a campaign goes to: the whole list, a tag, or a saved segment.

``audience`` is ``all``, ``tag:<choice>`` or ``segment:<id>``. A PATCH
validates it against the (new or current) list, ``schedule`` resolves it to
records filter terms and stores them on the render, and freeze reads them from
there: what a segment says later never changes a scheduled campaign. Errors
never repeat the submitted value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sm_records.contracts.newsletter import SubscriberFilterError, can_read_list
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_newsletter.campaigns.access import MAX_ID, Roles
from sm_newsletter.core.constants import TAGS_FIELD
from sm_newsletter.core.errors_audience import (
    InvalidAudience,
    SegmentListMismatch,
    UnknownSegment,
    UnknownTag,
)
from sm_newsletter.models import Segment
from sm_newsletter.segments.store import fields_for, filter_count

AUDIENCE_ALL = "all"
TAG_PREFIX = "tag:"
SEGMENT_PREFIX = "segment:"
MAX_TAG_LEN = 100
_CANONICAL_ID = re.compile(r"[1-9][0-9]*")


@dataclass(frozen=True)
class Audience:
    kind: Literal["all", "tag", "segment"]
    tag: str | None = None
    segment_id: int | None = None


def _control(text: str) -> bool:
    return any(ord(ch) < 32 or 127 <= ord(ch) < 160 for ch in text)


def parse_audience(raw: str) -> Audience:
    """The audience ``raw`` names; :class:`InvalidAudience` for any other form."""
    if raw == AUDIENCE_ALL:
        return Audience("all")
    if raw.startswith(TAG_PREFIX):
        tag = raw[len(TAG_PREFIX) :]
        if not tag or len(tag) > MAX_TAG_LEN or _control(tag):
            raise InvalidAudience()
        return Audience("tag", tag=tag)
    if raw.startswith(SEGMENT_PREFIX):
        digits = raw[len(SEGMENT_PREFIX) :]
        if not _CANONICAL_ID.fullmatch(digits) or len(digits) > 10:
            raise InvalidAudience()
        segment_id = int(digits)
        if segment_id > MAX_ID:
            raise InvalidAudience()
        return Audience("segment", segment_id=segment_id)
    raise InvalidAudience()


async def _tag_filters(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, tag: str
) -> list[str]:
    try:
        fields = await fields_for(session, tenant_id=tenant_id, list_type_key=list_type_key)
    except SubscriberFilterError:  # not a list (any more): it has no tags
        raise UnknownTag() from None
    field = fields.get(TAGS_FIELD)
    if field is None or not field.many or tag not in {c.value for c in field.choices}:
        raise UnknownTag()
    return [f"{TAGS_FIELD}:eq:{tag}"]


async def _segment_filters(
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    segment_id: int,
    roles: Roles,
    lock: bool,
) -> list[str]:
    stmt = select(col(Segment.list_type_key), col(Segment.filters)).where(
        col(Segment.id) == segment_id, col(Segment.tenant_id) == tenant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).first()
    if row is None:
        raise UnknownSegment()
    if row.list_type_key != list_type_key:
        # Only a caller who may read the segment's own list learns it exists.
        if not await can_read_list(
            session, tenant_id=tenant_id, type_key=row.list_type_key, roles=roles
        ):
            raise UnknownSegment()
        raise SegmentListMismatch()
    return list(row.filters)


async def audience_filters(
    session: AsyncSession,
    *,
    tenant_id: str,
    list_type_key: str,
    audience: str,
    roles: Roles,
    lock: bool = False,
) -> list[str]:
    """The records filter terms for ``audience`` on ``list_type_key``: none for
    the whole list. 422 ``unknown_tag``, ``unknown_segment`` or
    ``segment_list_mismatch`` when the list cannot answer it. ``roles`` is the
    caller (callers have already checked ``list_type_key`` is readable): a
    segment on another list it cannot read is ``unknown_segment``, like a
    missing one. ``lock`` takes the segment's row lock (a draft PATCH, so a
    concurrent ``delete_segment`` cannot miss the draft; a no-op on SQLite)."""
    parsed = parse_audience(audience)
    if parsed.kind == "all":
        return []
    key = {"tenant_id": tenant_id, "list_type_key": list_type_key}
    if parsed.kind == "tag":
        assert parsed.tag is not None  # noqa: S101 - narrows the type; an invariant, not input validation
        return await _tag_filters(session, **key, tag=parsed.tag)
    assert parsed.segment_id is not None  # noqa: S101 - narrows the type; an invariant, not input validation
    return await _segment_filters(
        session, **key, segment_id=parsed.segment_id, roles=roles, lock=lock
    )


async def audience_count(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, audience: str, roles: Roles
) -> int:
    """Confirmed subscribers of ``list_type_key`` in ``audience`` (suppressions
    not subtracted); 422 ``invalid_segment`` when records refuses a term."""
    filters = await audience_filters(
        session, tenant_id=tenant_id, list_type_key=list_type_key, audience=audience, roles=roles
    )
    return await filter_count(
        session, tenant_id=tenant_id, list_type_key=list_type_key, filters=filters
    )
