"""Bodies and answers of the sending API (rulings S2, S16, S17).

Bodies are parsed with ``parse_payload`` (campaigns schemas), so a 422 names
the field and never echoes the submitted value.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictInt


class ScheduleIn(BaseModel):
    """``scheduled_at`` left out means now (ruling S2)."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt
    scheduled_at: AwareDatetime | None = None


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt


class ProgressOut(BaseModel):
    status: str
    recipients: int
    queued: int
    sending: int
    sent: int
    failed: int
    bounced: int
    suppressed: int
    skipped: int
    cancelled: int
    paused_code: str | None
    paused_detail: str | None
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    estimated_finish: datetime | None
    daily_rate: int


class EstimateOut(BaseModel):
    # ``None``: a tag or segment audience and a caller without ``records.view``.
    recipients: int | None
    estimated_finish: datetime
    overlaps: bool
    daily_rate: int
