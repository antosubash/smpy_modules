"""The campaign report's response body: raw counts, the UI computes rates (T14)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LinkStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    url: str
    unique: int
    total: int


class PointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    at: datetime
    opens: int
    clicks: int


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    campaign_id: int
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    recipients: int
    sent: int
    failed: int
    bounced: int
    suppressed: int
    skipped: int
    unsubscribed: int
    opens_unique: int
    opens_total: int
    clicks_unique: int
    clicks_total: int
    opens_unique_accepted: int
    clicks_unique_accepted: int
    tracking_opens: bool
    tracking_clicks: bool
    links: list[LinkStatOut]
    bucket: Literal["hour", "day"]
    timeline: list[PointOut]
