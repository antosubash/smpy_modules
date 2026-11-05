"""Who may reach a campaign: records' list narrowing, on every request (ruling C4).

A campaign is only as visible as its list. Records owns the rule
(``allowed_roles``, widened by a ``records.type.<key>`` grant), so every
campaign read, list, write, preview, card refresh and test send asks it
through ``sm_records.contracts.newsletter`` with the caller's
:class:`CallerRoles` - not only when the list is chosen, since a list can be
narrowed after the campaign was written. A campaign on a list the caller may
not read answers 404, like one that does not exist: no existence oracle.
"""

from __future__ import annotations

from collections.abc import Sequence

from sm_records.contracts.newsletter import CallerRoles, can_read_list, subscription_lists
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.errors import ListForbidden, NotFound, UnknownList
from sm_newsletter.models import Campaign

Roles = Sequence[str] | CallerRoles | None
"""What records' ``can_read_list`` takes; ``None`` is no caller (a worker)."""


async def readable_lists(session: AsyncSession, *, tenant_id: str, roles: Roles) -> list[str]:
    """The tenant's newsletter lists this caller may read, sorted."""
    keys = await subscription_lists(session, tenant_id=tenant_id)
    return [
        key
        for key in keys
        if await can_read_list(session, tenant_id=tenant_id, type_key=key, roles=roles)
    ]


async def check_list(session: AsyncSession, *, tenant_id: str, type_key: str, roles: Roles) -> None:
    """Refuse a list a campaign is about to be put on: 422 ``unknown_list`` when
    the tenant has no such list, 403 ``list_forbidden`` when it is narrowed
    past this caller."""
    if type_key not in await subscription_lists(session, tenant_id=tenant_id):
        raise UnknownList()
    if not await can_read_list(session, tenant_id=tenant_id, type_key=type_key, roles=roles):
        raise ListForbidden()


async def require_campaign(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles
) -> Campaign:
    """The tenant's campaign ``campaign_id``, read fresh; :class:`NotFound` when
    there is none *or* its list is unreadable to this caller."""
    stmt = (
        select(Campaign)
        .where(Campaign.id == campaign_id, Campaign.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
    campaign = (await session.execute(stmt)).scalars().first()
    if campaign is None or not await can_read_list(
        session, tenant_id=tenant_id, type_key=campaign.list_type_key, roles=roles
    ):
        raise NotFound()
    return campaign
