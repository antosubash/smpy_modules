"""Bodies and answers of the suppressions API. Parsed with ``parse_payload``
(error ``invalid_query``), so a 422 never echoes an address or a note; no
answer carries an address, only a fingerprint of its hash."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from sm_newsletter.core.constants import LIFTABLE, MAX_EMAIL_LEN
from sm_newsletter.subscribers.suppressions import FINGERPRINT_LEN, SuppressionRow


class LookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LEN)


class LiftIn(BaseModel):
    """``note`` is checked by the lift itself (stripped, 1-500 characters)."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=1, max_length=MAX_EMAIL_LEN)
    note: str = Field(max_length=2000)


class SuppressionOut(BaseModel):
    id: int
    fingerprint: str
    reason: str
    list_type_key: str
    source: str
    created_at: datetime
    version: str
    liftable: bool
    """``reason in LIFTABLE``: the listing cannot know records' answer for an
    opt-out; the lift decides."""

    @classmethod
    def of(cls, row: SuppressionRow) -> SuppressionOut:
        return cls(
            id=row.id,
            fingerprint=row.email_hash[:FINGERPRINT_LEN],
            reason=row.reason,
            list_type_key=row.list_type_key,
            source=row.source,
            created_at=row.created_at,
            version=row.version,
            liftable=row.reason in LIFTABLE,
        )


class SuppressionPage(BaseModel):
    items: list[SuppressionOut]
    total: int
    counts: dict[str, int]


class LiftOut(BaseModel):
    id: int
    fingerprint: str
    reason: str
    list_type_key: str
    source: str
    suppressed_at: datetime
    lifted_at: datetime
    lifted_by: str | None
    note: str

    @classmethod
    def of(cls, lift) -> LiftOut:
        return cls(
            id=lift.id,
            fingerprint=lift.email_hash[:FINGERPRINT_LEN],
            reason=lift.reason,
            list_type_key=lift.list_type_key,
            source=lift.source,
            suppressed_at=lift.suppressed_at,
            lifted_at=lift.lifted_at,
            lifted_by=lift.lifted_by,
            note=lift.note,
        )


class LiftPage(BaseModel):
    items: list[LiftOut]
    total: int
