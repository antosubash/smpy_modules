"""The last time this tenant's subscriptions contacted a server, by the validated IP address.

The floor on how often one server is fetched cannot be keyed on the address the subscriber typed:
any number of names (wildcard subdomains, a trailing dot, a redirect) lead to one server. So the
fetch checks and writes this row, atomically, on the IP it is about to connect to, for the first
request and every redirect hop. No URL, host or secret is stored; the janitor deletes rows after a
day.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index
from sqlmodel import Field

from sm_events.models._base import Base
from sm_events.models._cols import big_pk, dt_required


class FetchTarget(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_fetch_target"
    __table_args__ = (
        Index("uq_events_fetch_target_ip", "tenant_id", "ip", unique=True),
        Index("ix_events_fetch_target_attempt", "last_attempt_at"),
    )

    id: int | None = big_pk()
    ip: str = Field(max_length=45)
    """A validated address, canonical form (an IPv6 one is at most 45 characters)."""
    last_attempt_at: datetime = dt_required()
