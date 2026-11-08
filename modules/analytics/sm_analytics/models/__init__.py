"""Analytics-owned tables, discovered by host migrations."""

from datetime import UTC, datetime
from uuid import uuid4

from simple_module_db import MultiTenantMixin, create_module_base
from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field

Base = create_module_base("analytics")


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class AnalyticsProperty(Base, MultiTenantMixin, table=True):
    __tablename__ = "analytics_property"
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    name: str = Field(max_length=100)
    kind: str = Field(default="public", max_length=20)
    origins: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    enabled: bool = False
    route_patterns: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    event_allowlist: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    utm_parameters: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class AnalyticsSession(Base, MultiTenantMixin, table=True):
    __tablename__ = "analytics_session"
    __table_args__ = (
        Index("ix_analytics_session_visitor", "tenant_id", "property_id", "visitor", "last_seen"),
        Index("ix_analytics_session_retention", "tenant_id", "last_seen", "id"),
    )
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    property_id: str = Field(foreign_key="analytics_property.id", max_length=36)
    visitor: str = Field(max_length=64)
    started_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)


class AnalyticsEvent(Base, MultiTenantMixin, table=True):
    __tablename__ = "analytics_event"
    __table_args__ = (
        UniqueConstraint("tenant_id", "property_id", "event_id", name="uq_analytics_event_id"),
        Index("ix_analytics_event_time", "tenant_id", "property_id", "created_at"),
        Index("ix_analytics_event_retention", "tenant_id", "created_at", "id"),
        *(
            Index(
                f"ix_analytics_event_{dimension}",
                "tenant_id",
                "property_id",
                dimension,
                "created_at",
            )
            for dimension in ("country", "region", "city", "path", "name")
        ),
    )
    id: str = Field(default_factory=new_id, primary_key=True, max_length=36)
    property_id: str = Field(foreign_key="analytics_property.id", max_length=36)
    session_id: str = Field(foreign_key="analytics_session.id", max_length=36, index=True)
    event_id: str = Field(max_length=36)
    visitor: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=utcnow)
    kind: str = Field(max_length=10)
    path: str = Field(max_length=500)
    name: str = Field(default="", max_length=50)
    properties: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    referrer: str = Field(default="", max_length=253)
    browser: str = Field(default="Other", max_length=30)
    os: str = Field(default="Other", max_length=30)
    device: str = Field(default="desktop", max_length=10)
    utm_source: str = Field(default="", max_length=200)
    utm_medium: str = Field(default="", max_length=200)
    utm_campaign: str = Field(default="", max_length=200)
    utm_term: str = Field(default="", max_length=200)
    utm_content: str = Field(default="", max_length=200)
    country: str = Field(default="", max_length=2)
    country_name: str = Field(default="", max_length=200)
    region: str = Field(default="", max_length=20)
    region_name: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=20)
    city_name: str = Field(default="", max_length=200)
