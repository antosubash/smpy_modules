"""Subscription request bodies (bounded, ``extra="forbid"``) and the response (never the URL)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from sm_events.core import constants
from sm_events.web.schemas._fields import Color, SingleLine, lower_color

__all__ = ["SubscriptionIn", "SubscriptionOut", "SubscriptionPatch"]

Label = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=constants.SUBSCRIPTION_LABEL_MAX
    ),
    SingleLine,
]
Minutes = Annotated[
    int,
    Field(
        ge=constants.SUBSCRIPTION_MIN_REFRESH_MINUTES, le=constants.SUBSCRIPTION_MAX_REFRESH_MINUTES
    ),
]


class SubscriptionIn(BaseModel):
    """The address is write-only and is judged by the service, not by a length here: a schema
    error would echo it back."""

    model_config = ConfigDict(extra="forbid")

    url: str
    label: Label
    color: Color | None = None
    refresh_minutes: Minutes | None = None
    public: bool = False

    _lower_color = field_validator("color", mode="before")(lower_color)


class SubscriptionPatch(BaseModel):
    """Only what is sent changes; an explicit ``null`` clears ``color`` and ``refresh_minutes``."""

    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    label: Label | None = None
    color: Color | None = None
    refresh_minutes: Minutes | None = None
    public: bool | None = None
    expected: Annotated[str, Field(max_length=constants.SUBSCRIPTION_VERSION_MAX)] | None = None
    """The ``version`` the caller read: another edit since is 409 ``stale``."""

    _lower_color = field_validator("color", mode="before")(lower_color)


class SubscriptionOut(BaseModel):
    """Everything a calendar's manager sees; never the address, the sealed value, the validators
    or the lease."""

    id: uuid.UUID
    calendar_id: uuid.UUID
    url_display: str
    label: str
    color: str | None
    refresh_minutes: int | None
    effective_refresh_minutes: int
    public: bool
    status: str
    error_code: str | None
    last_http_status: int | None
    last_fetched_at: datetime | None
    last_ok_at: datetime | None
    next_fetch_at: datetime | None
    consecutive_failures: int
    item_count: int
    last_counts: dict[str, Any]
    uses_internal_addresses: bool
    version: str
