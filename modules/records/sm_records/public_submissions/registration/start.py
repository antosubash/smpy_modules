"""When a registration's occurrence starts, as events resolves it now.

``sm_occurrence_start`` is a snapshot taken at submit: an organiser who moves the occurrence leaves
it stale, so "has it started" (cancelling, "my registrations") and the retention window ask events
(``summaries``, which applies moves and cancellations) and fall back to the snapshot only when
events cannot say (the event is gone or not public, or events is not installed).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sm_records.public_submissions.registration import seats

__all__ = ["keeps", "moment", "resolve_many", "resolved_start"]


def moment(value: Any) -> datetime | None:
    """A stored timestamp as an aware datetime, ``None`` when it is not one."""
    try:
        got = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return got if got.tzinfo else got.replace(tzinfo=UTC)


def _ref(data: dict[str, Any]) -> tuple[uuid.UUID, str] | None:
    try:
        return uuid.UUID(str(data["sm_event_id"])), str(data["sm_occurrence_key"])
    except (KeyError, ValueError):
        return None


async def resolve_many(
    db: Any, tenant_id: str, rows: list[dict[str, Any]]
) -> list[datetime | None]:
    """The start of each row's occurrence: events' resolved one, else the row's snapshot."""
    refs = {ref for data in rows if (ref := _ref(data)) is not None}
    facts: dict[Any, Any] = {}
    if refs and seats.available():
        facts = await seats.integration().summaries(
            db, tenant_id=tenant_id, refs=sorted(refs, key=str), locale="en"
        )
    out: list[datetime | None] = []
    for data in rows:
        found = facts.get(_ref(data))
        out.append(
            moment(found.starts_at)
            if found is not None
            else moment(data.get("sm_occurrence_start"))
        )
    return out


async def resolved_start(db: Any, tenant_id: str, data: dict[str, Any]) -> datetime | None:
    return (await resolve_many(db, tenant_id, [data]))[0]


async def keeps(db: Any, rtype: Any, record: Any, now: datetime) -> bool:
    """Whether retention must keep a registration the snapshot calls due: its occurrence, as events
    resolves it now, has not been over for ``retention_days`` yet (the event moved later)."""
    data = record.data or {}
    if data.get("sm_status") == "pending":
        return False  # a pending registration is due by its hold, not by the occurrence
    days = int((rtype.public_submissions or {}).get("retention_days", 365) or 0)
    start = await resolved_start(db, rtype.tenant_id, data)
    return days > 0 and start is not None and start + timedelta(days=days) >= now
