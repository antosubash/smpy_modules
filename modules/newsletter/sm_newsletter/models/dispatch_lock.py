"""The install-wide dispatch lock: one sending budget for the whole host.

**Deliberately not tenant-scoped** (no ``MultiTenantMixin``), like
``images_upload_admission``: the SMTP budget is the deployment's, and the row
holds nothing a tenant could read. The dispatcher upserts the singleton row
``"dispatch"`` on first use.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import dt_col


class DispatchLock(Base, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_dispatch_lock"

    name: str = Field(primary_key=True, max_length=32)
    holder: str | None = Field(default=None, max_length=64)
    locked_until: datetime | None = dt_col()
    updated_at: datetime = dt_col(nullable=False)
