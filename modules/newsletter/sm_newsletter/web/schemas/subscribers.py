"""Bodies and answers of the subscriber browse and detail (PR 6, Task 8).
The search body is parsed with ``parse_payload`` (error ``invalid_query``), so a
422 never echoes the search text."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sm_records.contracts.newsletter_admin import (
    MAX_BROWSE_LIMIT,
    MAX_BROWSE_OFFSET,
    MAX_SEARCH_LEN,
    BrowseStatus,
)

from sm_newsletter.campaigns.access import MAX_ID
from sm_newsletter.campaigns.audience import MAX_TAG_LEN
from sm_newsletter.subscribers.actions import MAX_TAG_VALUES
from sm_newsletter.subscribers.browse import SubscriberDetail, SubscriberRow
from sm_newsletter.subscribers.engagement import Engagement
from sm_newsletter.web.schemas.suppressions import SuppressionOut


class SubscriberSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: BrowseStatus | None = None
    # No NUL: records refuses it with a ``ValueError`` the browse does not catch (a 500).
    q: str | None = Field(default=None, max_length=MAX_SEARCH_LEN, pattern=r"^[^\x00]*$")
    tag: str | None = Field(default=None, min_length=1, max_length=MAX_TAG_LEN)
    segment: int | None = Field(default=None, ge=1, le=MAX_ID)
    offset: int = Field(default=0, ge=0, le=MAX_BROWSE_OFFSET)
    limit: int = Field(default=50, ge=1, le=MAX_BROWSE_LIMIT)


class SubscriberTagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    add: list[str] = Field(default_factory=list, max_length=MAX_TAG_VALUES)
    remove: list[str] = Field(default_factory=list, max_length=MAX_TAG_VALUES)


class EmptyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SubscriberOut(BaseModel):
    uuid: str
    email: str
    status: str
    first_name: str | None
    last_name: str | None
    tags: list[str]
    confirmed_at: datetime | None
    trashed: bool
    suppressed: bool

    @classmethod
    def of(cls, row: SubscriberRow) -> SubscriberOut:
        h = row.hit
        return cls(
            uuid=h.uuid,
            email=h.email,
            status=h.status,
            first_name=h.first_name,
            last_name=h.last_name,
            tags=list(h.tags),
            confirmed_at=h.confirmed_at,
            trashed=h.trashed,
            suppressed=row.suppressed,
        )


class SubscriberPageOut(BaseModel):
    items: list[SubscriberOut]
    total: int
    counts: dict[str, int]
    records_url: str


class SubscriberSuppressionOut(SuppressionOut):
    block: str | None
    """``None``: liftable now. Display only; the lift re-checks under its lock."""


class EngagementOut(BaseModel):
    campaigns_sent: int
    last_sent_at: datetime | None
    last_campaign_name: str | None
    opened_campaigns: int
    clicked_campaigns: int

    @classmethod
    def of(cls, e: Engagement) -> EngagementOut:
        return cls(**e.__dict__)


class SubscriberDetailOut(BaseModel):
    subscriber: SubscriberOut
    engagement: EngagementOut
    suppressions: list[SubscriberSuppressionOut]
    records_url: str

    @classmethod
    def of(cls, d: SubscriberDetail) -> SubscriberDetailOut:
        sup = [
            SubscriberSuppressionOut(**SuppressionOut.of(row).model_dump(), block=block)
            for row, block in d.suppressions
        ]
        return cls(
            subscriber=SubscriberOut.of(SubscriberRow(hit=d.hit, suppressed=d.suppressed)),
            engagement=EngagementOut.of(d.engagement),
            suppressions=sup,
            records_url=d.records_url,
        )
