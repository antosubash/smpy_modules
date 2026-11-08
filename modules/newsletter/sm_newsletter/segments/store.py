"""Saved segments: a named, compiled set of rules over one subscription list.

Every statement pins ``tenant_id``; a segment on a list the caller cannot read
is as absent as a missing one. A write validates in order: the list, the rules
(compiled against the list's fields), a dry-run count through records (which
refuses a term its index cannot answer), then stores ``rules`` and the compiled
``filters`` together.
"""

from __future__ import annotations

from simple_module_db import mark_written
from sm_records.contracts.newsletter import SubscriberFilterError, count_subscribers
from sm_records.contracts.newsletter_admin import ListField, list_fields
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns._refusal import DRAFT
from sm_newsletter.campaigns.access import Roles, check_list, readable_lists, require_list
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidSegment, SegmentInUse, SegmentNameTaken
from sm_newsletter.models import Campaign, Segment
from sm_newsletter.segments.rules import Rule, RuleError, compile_rules, segment_fields


async def fields_for(
    session: AsyncSession, *, tenant_id: str, list_type_key: str
) -> dict[str, ListField]:
    """The fields a rule on this list may name."""
    fields = await list_fields(session, tenant_id=tenant_id, type_key=list_type_key)
    return segment_fields(fields)


async def filter_count(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, filters: list[str]
) -> int:
    """Confirmed subscribers matching ``filters``; :class:`InvalidSegment` when
    records refuses a term."""
    try:
        return await count_subscribers(
            session, tenant_id=tenant_id, type_key=list_type_key, filters=filters
        )
    except SubscriberFilterError as exc:
        raise InvalidSegment(f"filter: {exc.reason}") from None


async def _compile(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, rules: list[Rule]
) -> tuple[list[str], int]:
    fields = await fields_for(session, tenant_id=tenant_id, list_type_key=list_type_key)
    try:
        filters = compile_rules(rules, fields)
    except RuleError as exc:
        raise InvalidSegment(str(exc)) from None
    count = await filter_count(
        session, tenant_id=tenant_id, list_type_key=list_type_key, filters=filters
    )
    return filters, count


async def _find(session: AsyncSession, *, tenant_id: str, segment_id: int) -> Segment | None:
    stmt = (
        select(Segment)
        .where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalars().first()


async def list_segments(
    session: AsyncSession, *, tenant_id: str, roles: Roles, list_type_key: str | None
) -> list[Segment]:
    readable = await readable_lists(session, tenant_id=tenant_id, roles=roles)
    if list_type_key is not None:
        readable = [k for k in readable if k == list_type_key]
    if not readable:
        return []
    stmt = (
        select(Segment)
        .where(Segment.tenant_id == tenant_id, Segment.list_type_key.in_(readable))
        .order_by(Segment.name, Segment.id)
    )
    return list((await session.execute(stmt)).scalars())


async def get_segment(
    session: AsyncSession, *, tenant_id: str, segment_id: int, roles: Roles
) -> Segment:
    segment = await _find(session, tenant_id=tenant_id, segment_id=segment_id)
    if segment is None:
        raise NotFound()
    await require_list(
        session, tenant_id=tenant_id, list_type_key=segment.list_type_key, roles=roles
    )
    return segment


async def _name_taken(
    session: AsyncSession, *, tenant_id: str, list_type_key: str, name: str, except_id: int | None
) -> bool:
    stmt = select(Segment.id).where(
        Segment.tenant_id == tenant_id,
        Segment.list_type_key == list_type_key,
        Segment.name == name,
    )
    if except_id is not None:
        stmt = stmt.where(Segment.id != except_id)
    return (await session.execute(stmt)).first() is not None


async def create_segment(
    session: AsyncSession,
    *,
    tenant_id: str,
    roles: Roles,
    name: str,
    list_type_key: str,
    rules: list[Rule],
) -> Segment:
    await check_list(session, tenant_id=tenant_id, type_key=list_type_key, roles=roles)
    filters, _ = await _compile(
        session, tenant_id=tenant_id, list_type_key=list_type_key, rules=rules
    )
    if await _name_taken(
        session, tenant_id=tenant_id, list_type_key=list_type_key, name=name, except_id=None
    ):
        raise SegmentNameTaken()
    segment = Segment(
        tenant_id=tenant_id,
        name=name,
        list_type_key=list_type_key,
        filters=filters,
        rules=[r.model_dump() for r in rules],
    )
    session.add(segment)
    try:
        await session.flush()
    except IntegrityError:
        raise SegmentNameTaken() from None
    return segment


async def update_segment(
    session: AsyncSession,
    *,
    tenant_id: str,
    segment_id: int,
    roles: Roles,
    name: str | None,
    rules: list[Rule] | None,
) -> Segment:
    segment = await get_segment(session, tenant_id=tenant_id, segment_id=segment_id, roles=roles)
    values: dict[str, object] = {}
    if rules is not None:
        values["filters"], _ = await _compile(
            session, tenant_id=tenant_id, list_type_key=segment.list_type_key, rules=rules
        )
        values["rules"] = [r.model_dump() for r in rules]
    if name is not None and name != segment.name:
        if await _name_taken(
            session,
            tenant_id=tenant_id,
            list_type_key=segment.list_type_key,
            name=name,
            except_id=segment_id,
        ):
            raise SegmentNameTaken()
        values["name"] = name
    if values:
        for key, value in values.items():
            setattr(segment, key, value)
        try:
            await session.flush()
        except IntegrityError:
            raise SegmentNameTaken() from None
    return segment


async def delete_segment(
    session: AsyncSession, *, tenant_id: str, segment_id: int, roles: Roles
) -> None:
    await get_segment(session, tenant_id=tenant_id, segment_id=segment_id, roles=roles)
    in_use = await session.execute(
        select(Campaign.id)
        .where(
            Campaign.tenant_id == tenant_id,
            Campaign.status == DRAFT,
            Campaign.audience == f"segment:{segment_id}",
        )
        .limit(1)
    )
    if in_use.first() is not None:
        raise SegmentInUse()
    await session.execute(
        delete(Segment)
        .where(Segment.id == segment_id, Segment.tenant_id == tenant_id)
        .execution_options(synchronize_session=False)
    )
    mark_written(session)


async def preview(
    session: AsyncSession, *, tenant_id: str, roles: Roles, list_type_key: str, rules: list[Rule]
) -> int:
    await check_list(session, tenant_id=tenant_id, type_key=list_type_key, roles=roles)
    _, count = await _compile(
        session, tenant_id=tenant_id, list_type_key=list_type_key, rules=rules
    )
    return count
