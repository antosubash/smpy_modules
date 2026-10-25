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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import SubmissionDelivery

__all__ = ["forget_deliveries"]


async def forget_deliveries(
    db: AsyncSession, tenant: str, uuids: Any, *, lock: Any = None, table: Any = None
) -> None:
    """Delete every claim of the records ``uuids`` (a select of uuids) names.

    With ``lock`` (a predicate over ``table``, the records being purged), the
    rows are first locked ``FOR UPDATE``: a confirmation task claiming a
    recipient holds a share lock on its record row while it inserts the
    claim (``public_submissions.delivery.claim``), so a claim either commits
    before this and is deleted here, or finds the record gone and never sends.
    """
    if lock is not None and table is not None:
        rows = (
            select(table.id)
            .where(lock, table.tenant_id == tenant)
            .with_for_update()
            .execution_options(include_deleted=True)
        )
        await db.execute(rows)
    claims = SubmissionDelivery
    await db.execute(
        sa_delete(claims)
        .where(claims.tenant_id == tenant, claims.record_uuid.in_(uuids))
        .execution_options(synchronize_session=False)
    )
