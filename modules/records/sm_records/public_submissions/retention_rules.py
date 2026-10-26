"""When a website submission is due for deletion (#101, design §10): the
retention window per kind, and the re-check made under the lock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sm_records.contracts.public_submissions import KIND_FORM
from sm_records.models import RecordType

__all__ = ["PENDING", "days_for", "still_due"]

PENDING: Final = "pending"


def days_for(config: dict[str, Any]) -> int:
    if config.get("kind") == KIND_FORM:
        return int(config.get("retention_days", 365) or 0)
    return max(1, int(config.get("pending_purge_days", 30) or 30))


def _moment(value: Any) -> datetime | None:
    """A stored timestamp as an aware datetime (SQLite hands back naive UTC,
    and the payload holds ISO text)."""
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def still_due(rtype: RecordType, record: Any, now: datetime) -> bool:
    """Whether the locked ``record`` is due *now*: a form submission past
    retention, or a subscriber still pending past the window that opened when
    they last entered pending."""
    config = rtype.public_submissions or {}
    cutoff = now - timedelta(days=days_for(config))
    created = _moment(record.created_at) if record.created_at else None
    if created is None or created >= cutoff:
        return False
    if config.get("kind") == KIND_FORM:
        return True
    data = record.data or {}
    if data.get("sm_status") != PENDING:
        return False
    entered = (_moment(data["sm_consent_at"]) if data.get("sm_consent_at") else None) or created
    return entered < cutoff
