"""Pydantic request/response models for the billing API."""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from sm_billing.constants import Interval, PricingModel, SubscriptionStatus

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_LIMIT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")
# Stored in int4 columns (amounts, limits); keep well inside 2**31 - 1.
MAX_AMOUNT = 2_000_000_000
MAX_SORT_ORDER = 1_000_000
RETURN_URL_MAX = 255
RETURN_URL_RULE = (
    "Return URL must be an http(s) origin such as https://app.example.com — "
    f"no path, query or fragment, at most {RETURN_URL_MAX} characters."
)
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$|^\[[0-9A-Fa-f:.]+\]$")
_CONTROL_RE = re.compile(r"[\x00-\x20\x7f]")


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
    amount_month: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    amount_year: int | None = Field(default=None, ge=0, le=MAX_AMOUNT)
    stripe_price_month: str | None = Field(default=None, max_length=255)
    stripe_price_year: str | None = Field(default=None, max_length=255)
    trial_days: int = Field(default=0, ge=0, le=730)
    limits: dict[str, int] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    is_default: bool = False
    is_public: bool = True
    sort_order: int = Field(default=0, ge=-MAX_SORT_ORDER, le=MAX_SORT_ORDER)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("key must be 1-64 chars of a-z, 0-9, '-' or '_'")
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
            if limit > MAX_AMOUNT:
                raise ValueError(f"limit for {key!r} must be <= {MAX_AMOUNT}")
        return value

    @field_validator("features")
    @classmethod
    def _features(cls, value: list[str]) -> list[str]:
        cleaned = sorted({f.strip() for f in value if f.strip()})
        for feature in cleaned:
            if not _LIMIT_KEY_RE.match(feature):
                raise ValueError(f"invalid feature key {feature!r}")
        return cleaned


class PlanOut(BaseModel):
    """A stored plan as the API returns it.

    Deliberately not a ``PlanIn`` subclass: input bounds and validators guard
    writes, and a row stored before a bound existed must still be readable —
    otherwise one legacy value 500s every screen that lists plans.
    """

    id: int
    key: str
    name: str
    description: str
    pricing_model: PricingModel
    currency: str
    amount_month: int | None
    amount_year: int | None
    stripe_price_month: str | None
    stripe_price_year: str | None
    trial_days: int
    limits: dict[str, int]
    features: list[str]
    is_default: bool
    is_public: bool
    sort_order: int
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
    # Validated by ``normalise_return_url`` so a bad value is a 400 with a
    # readable message, not a raw 422.
    return_base_url: str = ""


def normalise_return_url(value: str) -> str:
    """Blank, or an http(s) origin without a trailing "/". ``ValueError`` otherwise."""
    value = value.strip()
    if not value:
        return ""
    # Whitespace/control characters first: urlsplit drops \t \n \r silently,
    # so they would pass every check below and be stored verbatim.
    if len(value) > RETURN_URL_MAX or _CONTROL_RE.search(value):
        raise ValueError(RETURN_URL_RULE)
    try:
        parts = urlsplit(value)
        port_ok = parts.port is None or parts.port > 0
    except ValueError as exc:
        raise ValueError(RETURN_URL_RULE) from exc
    netloc_host = parts.netloc.rsplit(":", 1)[0] if parts.port else parts.netloc
    if (
        parts.scheme.lower() not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or not _HOST_RE.match(netloc_host)
        or not port_ok
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
    ):
        raise ValueError(RETURN_URL_RULE)
    return value.rstrip("/")


class ConnectionOut(BaseModel):
    provider: str
    active_provider: str
    provider_error: str
    has_secret_key: bool
    has_webhook_secret: bool
    return_base_url: str
    webhook_path: str


class SubscriptionRow(BaseModel):
    """One tenant on the admin subscriptions screen (tenants without a row too)."""

    tenant_id: str
    tenant_name: str
    tenant_slug: str
    tenant_status: str
    members: int
    plan_id: int
    plan_key: str
    plan_name: str
    status: SubscriptionStatus | None
    interval: Interval | None
    quantity: int | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    suspended_by_billing: bool
    provider_subscription_id: str | None
    synced_at: datetime | None
