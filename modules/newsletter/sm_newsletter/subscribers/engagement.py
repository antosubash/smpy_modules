"""What one subscriber did with the campaigns sent to them (PR 6, Task 8).

G15: aggregates only. There is no per-send list and no campaign id here, so the
console never shows which campaign a person opened. ``opened`` is approximate
(an image-loading proxy opens a mail for its recipient), as PR 5's wording says.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Integer, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send

__all__ = ["Engagement", "engagement"]

_S = Send.__table__


@dataclass(frozen=True)
class Engagement:
    campaigns_sent: int
    last_sent_at: datetime | None
    last_campaign_name: str | None
    opened_campaigns: int
    clicked_campaigns: int


def _count(condition) -> object:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0).cast(Integer)


async def engagement(session: AsyncSession, *, tenant_id: str, record_uuid: str) -> Engagement:
    """Aggregates over the tenant's send rows of ``record_uuid``; zeros for none."""
    pin = [_S.c.tenant_id == tenant_id, _S.c.record_uuid == record_uuid]
    with tenant_scope(tenant_id):
        agg = select(
            _count(_S.c.status == "sent"),
            func.max(_S.c.sent_at).filter(_S.c.status == "sent"),
            _count(_S.c.opened_at.is_not(None)),
            _count(_S.c.first_clicked_at.is_not(None)),
        ).where(*pin)
        sent, last_sent_at, opened, clicked = (await session.execute(agg)).one()
        name = None
        if sent:
            latest = (
                select(Campaign.name)
                .join(_S, _S.c.campaign_id == Campaign.id)
                .where(*pin, _S.c.status == "sent", Campaign.tenant_id == tenant_id)
                .order_by(_S.c.sent_at.desc(), _S.c.id.desc())
                .limit(1)
            )
            name = (await session.execute(latest)).scalar_one_or_none()
    return Engagement(
        campaigns_sent=int(sent),
        last_sent_at=last_sent_at,
        last_campaign_name=name,
        opened_campaigns=int(opened),
        clicked_campaigns=int(clicked),
    )
