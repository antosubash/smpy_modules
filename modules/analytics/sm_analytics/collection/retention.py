"""Bounded retention and explicit operator maintenance."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_analytics.models import AnalyticsEvent as E
from sm_analytics.models import AnalyticsSession as S


async def cleanup(
    db: AsyncSession,
    tenant: str,
    *,
    now: datetime,
    retention_days: int = 90,
    batch_size: int = 5000,
) -> int:
    cutoff = now - timedelta(days=retention_days)
    ids = select(E.id).where(E.tenant_id == tenant, E.created_at < cutoff).limit(batch_size)
    result = await db.execute(delete(E).where(E.tenant_id == tenant, E.id.in_(ids)))
    sessions = (
        select(S.id)
        .where(
            S.tenant_id == tenant,
            S.last_seen < cutoff,
            ~select(E.id).where(E.tenant_id == tenant, E.session_id == S.id).exists(),
        )
        .limit(batch_size)
    )
    await db.execute(delete(S).where(S.tenant_id == tenant, S.id.in_(sessions)))
    return result.rowcount
