"""Write-ahead intent for an object, so the janitor can reap crash/rollback orphans.

**Deliberately not tenant-scoped.** No ``MultiTenantMixin``: the janitor is a
platform reaper that must see every tenant's intents in one query, and the key
already embeds the tenant. ``simple_module_db`` applies its tenant filter, stamp
and strict-mode refusal only to ``MultiTenantMixin`` subclasses (``isinstance``
checks in ``flush_guard``/``query_filter``), so this table is unaffected by
strict tenancy: reads are unfiltered and inserts need no bound tenant.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.types import AwareDateTime
from sqlmodel import Field

from sm_images.clock import utcnow
from sm_images.models._base import Base


class ObjectIntent(Base, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_object_intent"

    key: str = Field(primary_key=True, max_length=500)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=AwareDateTime(),
        sa_column_kwargs={"nullable": False, "index": True},
    )
    attempted_at: datetime | None = Field(
        default=None, sa_type=AwareDateTime(), sa_column_kwargs={"nullable": True}
    )
    """When the intent reaper last failed to delete the object: such intents
    go to the back of later passes, so one stuck key cannot starve the rest."""
