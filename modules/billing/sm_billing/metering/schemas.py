"""Request and response models for the usage screens and their API.

The ``*Out`` models carry no bounds or validators: a stored row that
predates a bound must still be readable (CLAUDE.md), so the bounds live on
the ``*In`` models only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from sm_billing.metering.validate import METER_MAX, QTY_MAX

REASON_MAX = 500


class MeterUsageOut(BaseModel):
    """One meter on the tenant's usage card.

    Counters: ``used`` this period and when it resets (``period_end``).
    Gauges: ``used`` is the level held now, ``holds`` how many holds make it
    up, and the period fields are ``None`` (a gauge never resets).
    """

    meter: str
    kind: str
    unit: str
    label_key: str
    used: int
    limit: int | None
    period_start: datetime | None
    period_end: datetime | None
    holds: int | None


class UsageRowOut(BaseModel):
    """One tenant x meter on the admin usage table."""

    tenant_id: str
    tenant_name: str
    tenant_slug: str
    meter: str
    kind: str
    unit: str
    label_key: str
    registered: bool
    used: int
    limit: int | None
    #: ``used / limit`` in percent; ``None`` when the plan sets no limit.
    percent: float | None
    period_start: datetime | None
    period_end: datetime | None


class UsagePageOut(BaseModel):
    items: list[UsageRowOut]
    total: int
    page: int
    per_page: int
    pages: int


class UsageEventOut(BaseModel):
    id: int
    meter: str
    kind: str
    quantity: int
    idempotency_key: str
    source: str
    actor: str | None
    reason: str | None
    period_start: datetime | None
    occurred_at: datetime
    recorded_at: datetime


class UsageEventPageOut(BaseModel):
    items: list[UsageEventOut]
    total: int
    page: int
    per_page: int
    pages: int


class UsageHoldOut(BaseModel):
    id: str
    meter: str
    quantity: int
    status: str
    idempotency_key: str
    source: str
    expires_at: datetime | None
    created_at: datetime
    settled_at: datetime | None


class MeterOut(BaseModel):
    """A registered meter, for the admin screen's filter and dialogs."""

    key: str
    kind: str
    unit: str
    label_key: str


class AdjustIn(BaseModel):
    """An operator's signed correction to a counter's current period."""

    meter: str = Field(min_length=1, max_length=METER_MAX)
    quantity: int = Field(ge=-QTY_MAX, le=QTY_MAX)
    reason: str = Field(max_length=REASON_MAX)

    @field_validator("quantity")
    @classmethod
    def _non_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("quantity must not be 0")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a reason is required")
        return value


class AdjustOut(BaseModel):
    meter: str
    used: int


class RecountIn(BaseModel):
    meter: str = Field(min_length=1, max_length=METER_MAX)


class RecountOut(BaseModel):
    meter: str
    in_use: int


class ReleaseOut(BaseModel):
    #: ``False`` when the hold was settled already (released or expired).
    released: bool


Period = Literal["current", "previous"]
