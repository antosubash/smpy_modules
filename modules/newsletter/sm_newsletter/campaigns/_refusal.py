"""Why a conditional campaign write matched nothing, read after the fact.

Every campaign write (a draft change, a lifecycle transition) is one
conditional ``UPDATE`` or ``DELETE``; when it changes no row, the campaign is
read again to say why (rulings C3, S14). Reading afterwards, never before, is
what lets two racing callers both be answered correctly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.errors import InvalidTransition, NotADraft, NotFound, StaleCampaign
from sm_newsletter.models import Campaign

DRAFT = "draft"


async def refusal(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    from_statuses: tuple[str, ...] = (DRAFT,),
    pinned_revision: bool = True,
) -> Exception:
    """The error for a write that required ``from_statuses`` (and, with
    ``pinned_revision``, the revision the caller read):

    * the campaign is gone: :class:`NotFound`;
    * its status is not one of ``from_statuses``: :class:`NotADraft` for a
      draft-only write, else :class:`InvalidTransition`;
    * otherwise it moved on: :class:`StaleCampaign` for a revision-pinned
      write, else :class:`InvalidTransition`.
    """
    stmt = select(Campaign.status).where(
        Campaign.id == campaign_id, Campaign.tenant_id == tenant_id
    )
    status = (await session.execute(stmt)).scalars().first()
    if status is None:
        return NotFound()
    if status not in from_statuses:
        return NotADraft() if from_statuses == (DRAFT,) else InvalidTransition()
    return StaleCampaign() if pinned_revision else InvalidTransition()
