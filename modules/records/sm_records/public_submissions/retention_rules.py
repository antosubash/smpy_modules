"""When a website submission is due for deletion (#101, design §10): the
retention window per kind, and the re-check made under the lock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sm_records.contracts.public_submissions import KIND_FORM, KIND_REGISTRATION
from sm_records.models import RecordType

__all__ = ["PENDING", "days_for", "still_due", "window_for"]

PENDING: Final = "pending"


def days_for(config: dict[str, Any]) -> int:
    if config.get("kind") == KIND_FORM:
        return int(config.get("retention_days", 365) or 0)
    return max(1, int(config.get("pending_purge_days", 30) or 30))


def window_for(config: dict[str, Any]) -> timedelta | None:
    """How long after it was created a record of this type can first be due, or ``None`` when it
    never is: the candidate query's cutoff. A registration is due when its pending hold runs out or,
    with ``retention_days``, that long after its occurrence (which is never before it was made)."""
    if config.get("kind") == KIND_REGISTRATION:
        hold = timedelta(hours=int(config.get("pending_hold_hours", 24) or 24))
        days = int(config.get("retention_days", 365) or 0)
        return min(hold, timedelta(days=days)) if days > 0 else hold
    days = days_for(config)
    return timedelta(days=days) if days > 0 else None


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
    if config.get("kind") == KIND_REGISTRATION:
        return _registration_due(config, record, now)
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


def _registration_due(config: dict[str, Any], record: Any, now: datetime) -> bool:
    """A registration still ``pending`` is due once ``pending_hold_hours`` have passed since its
    consent (the seat it held goes with it); any other is due ``retention_days`` after its
    occurrence's start (``0`` keeps it), cancelled ones included."""
    data = record.data or {}
    created = _moment(record.created_at) if record.created_at else None
    if data.get("sm_status") == PENDING:
        entered = (_moment(data["sm_consent_at"]) if data.get("sm_consent_at") else None) or created
        hold = timedelta(hours=int(config.get("pending_hold_hours", 24) or 24))
        return entered is not None and entered + hold < now
    days = int(config.get("retention_days", 365) or 0)
    if days <= 0:
        return False
    start = (
        _moment(data["sm_occurrence_start"]) if data.get("sm_occurrence_start") else None
    ) or created
    return start is not None and start + timedelta(days=days) < now
