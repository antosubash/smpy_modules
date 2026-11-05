"""Draft campaigns: create, read, list, change and delete.

Every statement pins ``Campaign.tenant_id`` itself (on a single-tenant host the
framework's filter does nothing), and every campaign goes through
:mod:`~sm_newsletter.campaigns.access` with the caller's roles.

A change is one conditional ``UPDATE`` (ruling C3): it matches only the draft
at the revision the editor read, and bumps the revision. Zero rows means the
campaign is gone (404), no longer a draft (409 ``not_a_draft``) or moved on
(409 ``stale``) - decided by reading it again, after the fact, so two editors
racing each other cannot both win. Delete is conditional the same way.
"""

from __future__ import annotations

from typing import Any

from simple_module_db import mark_written
from simple_module_db.listeners import current_user_id
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles, check_list, readable_lists, require_campaign
from sm_newsletter.content.blocks import dump_body, parse_body
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import AudienceUnsupported, NotADraft, NotFound, StaleCampaign
from sm_newsletter.models import Campaign
from sm_newsletter.web.schemas.campaigns import CampaignCreate, CampaignPatch

DRAFT = "draft"
AUDIENCE_ALL = "all"
MAX_PAGE = 100


async def create_draft(
    session: AsyncSession, *, tenant_id: str, data: CampaignCreate, roles: Roles
) -> Campaign:
    await check_list(session, tenant_id=tenant_id, type_key=data.list_type_key, roles=roles)
    now = utcnow()
    campaign = Campaign(
        tenant_id=tenant_id,
        name=data.name,
        list_type_key=data.list_type_key,
        subject=data.subject,
        preheader=data.preheader,
        created_at=now,
        # Set on insert too, so the list's newest-first order needs no NULL rule.
        updated_at=now,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def get_campaign(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles
) -> Campaign:
    return await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_campaigns(
    session: AsyncSession,
    *,
    tenant_id: str,
    roles: Roles,
    status: str | None,
    q: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Campaign], int]:
    """One page, newest change first, of the campaigns on lists the caller may
    read, and how many there are in all."""
    readable = await readable_lists(session, tenant_id=tenant_id, roles=roles)
    if not readable:
        return [], 0
    where: list[Any] = [Campaign.tenant_id == tenant_id, Campaign.list_type_key.in_(readable)]
    if status:
        where.append(Campaign.status == status)
    if q:
        where.append(Campaign.name.ilike(f"%{_escape_like(q)}%", escape="\\"))
    total = await session.scalar(select(func.count()).select_from(Campaign).where(*where))
    stmt = (
        select(Campaign)
        .where(*where)
        .order_by(Campaign.updated_at.desc(), Campaign.id.desc())
        .offset(max(offset, 0))
        .limit(max(min(limit, MAX_PAGE), 1))
    )
    return list((await session.execute(stmt)).scalars()), int(total or 0)


async def _refusal(session: AsyncSession, *, tenant_id: str, campaign_id: int) -> Exception:
    """Why a conditional write matched nothing, read after the fact."""
    stmt = select(Campaign.status).where(
        Campaign.id == campaign_id, Campaign.tenant_id == tenant_id
    )
    status = (await session.execute(stmt)).scalars().first()
    if status is None:
        return NotFound()
    return NotADraft() if status != DRAFT else StaleCampaign()


async def update_draft(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    patch: CampaignPatch,
    roles: Roles,
) -> Campaign:
    current = await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )
    values = patch.changes()
    key = values.get("list_type_key")
    if key is not None and key != current.list_type_key:
        await check_list(session, tenant_id=tenant_id, type_key=key, roles=roles)
    if values.get("audience", AUDIENCE_ALL) != AUDIENCE_ALL:
        raise AudienceUnsupported()
    if "body" in values:
        values["body"] = dump_body(parse_body(values["body"]))
    return await write_draft(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        expected_revision=patch.expected_revision,
        values=values,
        roles=roles,
    )


async def write_draft(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    expected_revision: int,
    values: dict[str, Any],
    roles: Roles,
) -> Campaign:
    """Write already-validated ``values`` onto the draft at ``expected_revision``
    and bump its revision: the one conditional ``UPDATE`` every draft change
    (PATCH, card refresh) goes through. Zero rows raises the reason."""
    stmt = (
        update(Campaign)
        .where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
            Campaign.status == DRAFT,
            Campaign.revision == expected_revision,
        )
        # A Core-style UPDATE skips the audit listener: stamp what it would.
        .values(
            **values,
            revision=Campaign.revision + 1,
            updated_at=utcnow(),
            updated_by=current_user_id.get(),
        )
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    mark_written(session)
    if result.rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise await _refusal(session, tenant_id=tenant_id, campaign_id=campaign_id)
    return await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )


async def delete_draft(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles
) -> None:
    await require_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles)
    stmt = (
        delete(Campaign)
        .where(
            Campaign.id == campaign_id,
            Campaign.tenant_id == tenant_id,
            Campaign.status == DRAFT,
        )
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    mark_written(session)
    if result.rowcount != 1:  # ty: ignore[unresolved-attribute]
        raise await _refusal(session, tenant_id=tenant_id, campaign_id=campaign_id)
