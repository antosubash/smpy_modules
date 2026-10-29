"""One row per tenant that serialises the admission of new direct and ZIP uploads.

``ingest.admission`` writes this row (an upsert, then an ``UPDATE``) before it
counts the tenant's open uploads, in the same transaction that then inserts the
new ``images_upload_session`` row. The write takes the row lock on Postgres and
the database write lock on SQLite, held until that transaction commits, so two
concurrent opens can never both count the same "one slot left".

**Deliberately not tenant-scoped** (no ``MultiTenantMixin``): ``tenant`` *is*
the key, and the row holds nothing a tenant could read.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db.types import AwareDateTime
from sqlalchemy import BigInteger
from sqlmodel import Field

from sm_images.clock import utcnow
from sm_images.models._base import Base


class UploadAdmission(Base, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_upload_admission"

    tenant: str = Field(primary_key=True, max_length=255)
    admitted: int = Field(default=0, sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    """How many uploads were ever admitted: the counter the lock's write bumps."""
    updated_at: datetime = Field(
        default_factory=utcnow, sa_type=AwareDateTime(), sa_column_kwargs={"nullable": False}
    )
