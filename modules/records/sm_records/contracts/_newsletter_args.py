"""The newsletter contract's argument checks and its DTO (newsletter PR 2 split).

Moved out of :mod:`sm_records.contracts.newsletter` unchanged (#133); that
module stays the import path and re-exports :class:`SubscriberHit` and
:data:`MAX_SUBSCRIBER_BATCH`. Every check raises ``ValueError`` before a
query runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, cast

from simple_module_db import is_valid_tenant_id
from sqlmodel import SQLModel

from sm_records.models import Record, RecordType
from sm_records.public_submissions import campaign_reads, campaign_writes
from sm_records.public_submissions.campaign_reads import moment, stored_tags
from sm_records.public_submissions.subscribe import UNSUBSCRIBED

Status = Literal["confirmed", "unsubscribed"]

MAX_SUBSCRIBER_BATCH = 1000
"""The most subscribers one call returns or looks up."""


class SubscriberHit(SQLModel):
    uuid: str
    email: str
    locale: str
    status: str  # "pending" | "confirmed" | "unsubscribed"
    confirmed_at: datetime | None
    first_name: str | None = None
    last_name: str | None = None
    tags: list[str] = []
    trashed: bool = False


def _checked_limit(limit: object) -> int:
    # `bool` is an `int`; `True` as a limit is a caller bug, not "one row".
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_SUBSCRIBER_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_SUBSCRIBER_BATCH}, got {limit}")
    return limit


def _checked_after(after: object) -> int:
    if not isinstance(after, int) or isinstance(after, bool) or after < 0:
        raise ValueError(f"after must be a non-negative int, got {after!r}")
    return after


def _checked_status(status: object) -> Status:
    if status not in campaign_reads.WALKABLE:
        raise ValueError(f"status must be one of {campaign_reads.WALKABLE}, got {status!r}")
    return cast(Status, str(status))


def _checked_trash(include_trashed: object, status: str) -> bool:
    """``include_trashed`` is a ``bool``, and ``True`` only for the
    ``unsubscribed`` walk: the trash is never anybody's audience."""
    if not isinstance(include_trashed, bool):
        raise ValueError(f"include_trashed must be a bool, got {include_trashed!r}")
    if include_trashed and status != UNSUBSCRIBED:
        raise ValueError(f"include_trashed needs status={UNSUBSCRIBED!r}, got {status!r}")
    return include_trashed


def _checked_tags(tags: Sequence[str], name: str) -> list[str]:
    # A bare string is a sequence of one-letter tags: a caller bug.
    if isinstance(tags, str) or not all(isinstance(t, str) for t in tags):
        raise ValueError(f"{name} must be a sequence of tag strings, not {tags!r}")
    return list(tags)


def _checked_tenant(tenant_id: object) -> str:
    # is_valid_tenant_id refuses every non-str; isinstance tells the checker.
    if not isinstance(tenant_id, str) or not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _hit(rtype: RecordType, record: Record) -> SubscriberHit:
    declared = {f.get("key") for f in rtype.fields or []}
    data = record.data or {}
    tags = data.get(campaign_writes.TAGS) if campaign_writes.TAGS in declared else None
    return SubscriberHit(
        uuid=record.uuid,
        email=str(data.get("sm_email") or ""),
        locale=str(data.get("sm_locale") or ""),
        status=str(data.get("sm_status") or ""),
        confirmed_at=moment(data.get("sm_confirmed_at")),
        first_name=_text(data.get("first_name")) if "first_name" in declared else None,
        last_name=_text(data.get("last_name")) if "last_name" in declared else None,
        tags=stored_tags(tags),
        trashed=bool(record.is_deleted),
    )
