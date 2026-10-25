"""A purged record's delivery claims go with it (#101).

``records_submission_delivery`` names who a submission's mail reached — a
staff address, or a subscriber's keyed hash — beside the record's uuid and
when. That outlives nothing it describes: whatever purges a record (one
purge, the trash emptied, the type deleted) deletes its claims in the same
transaction, so an erasure leaves no trace of the address there.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import SubmissionDelivery

__all__ = ["forget_deliveries"]


async def forget_deliveries(db: AsyncSession, tenant: str, uuids: Any) -> None:
    """Delete every claim of the records ``uuids`` (a select of uuids) names."""
    table = SubmissionDelivery
    await db.execute(
        sa_delete(table)
        .where(table.tenant_id == tenant, table.record_uuid.in_(uuids))
        .execution_options(synchronize_session=False)
    )
