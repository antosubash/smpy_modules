"""Pydantic request/response models for the billing API."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from sm_billing.constants import Interval, PricingModel, SubscriptionStatus

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LIMIT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class PlanIn(BaseModel):
    key: str
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    pricing_model: PricingModel
    currency: str = Field(default="eur", min_length=3, max_length=3)
    amount_month: int | None = Field(default=None, ge=0)
    amount_year: int | None = Field(default=None, ge=0)
    stripe_price_month: str | None = Field(default=None, max_length=255)
    stripe_price_year: str | None = Field(default=None, max_length=255)
    trial_days: int = Field(default=0, ge=0, le=730)
    limits: dict[str, int] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    is_default: bool = False
    is_public: bool = True
    sort_order: int = 0

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("key must be 1–64 chars of a-z, 0-9, '-' or '_'")
        return value

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return value.lower()

    @field_validator("stripe_price_month", "stripe_price_year", mode="before")
    @classmethod
    def _prices(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("limits")
    @classmethod
    def _limits(cls, value: dict[str, int]) -> dict[str, int]:
        for key, limit in value.items():
            if not _LIMIT_KEY_RE.match(key):
                raise ValueError(f"invalid limit key {key!r}")
            if limit < 0:
                raise ValueError(f"limit for {key!r} must be >= 0")
        return value

    @field_validator("features")
    @classmethod
    def _features(cls, value: list[str]) -> list[str]:
        cleaned = sorted({f.strip() for f in value if f.strip()})
        for feature in cleaned:
            if not _LIMIT_KEY_RE.match(feature):
                raise ValueError(f"invalid feature key {feature!r}")
        return cleaned


class PlanOut(PlanIn):
    id: int
    archived_at: datetime | None = None


class SubscriptionOut(BaseModel):
    status: SubscriptionStatus | None
    interval: Interval | None
    quantity: int
    trial_end: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    has_provider_subscription: bool


class StatusOut(BaseModel):
    plan: PlanOut
    subscription: SubscriptionOut | None
    seats: dict[str, int | None]
    provider: str
    checkout_available: bool
    portal_available: bool


class PlanChoice(BaseModel):
    plan_id: int
    interval: Interval = Interval.MONTH


class UrlOut(BaseModel):
    url: str


class AssignIn(BaseModel):
    plan_id: int
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    interval: Interval | None = None


class ConnectionIn(BaseModel):
    """Empty string = keep the stored value; ``clear_*`` wins over a value."""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    clear_secret_key: bool = False
    clear_webhook_secret: bool = False
    return_base_url: str = Field(default="", max_length=255)


class ConnectionOut(BaseModel):
    provider: str
    active_provider: str
    provider_error: str
    has_secret_key: bool
    has_webhook_secret: bool
    return_base_url: str
    webhook_path: str
