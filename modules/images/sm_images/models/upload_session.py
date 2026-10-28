"""Direct-upload sessions: the authoritative state of a multipart upload.

The signed ``upload_id`` the client holds is only a handle (it carries this
row's ``id``); what a ``complete`` or ``abort`` may do is decided here, by a
compare-and-set on ``status`` (``sm_images.ingest.upload_session``). The row
also holds what the reaper needs to reclaim an abandoned upload: the backend's
multipart id, the staged key and when the upload expires.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from simple_module_db.types import AwareDateTime
from sqlalchemy import BigInteger, Column, Index, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import enum_col, fk_uuid, pk_uuid
from sm_images.models.enums import UploadStatus

UPLOAD_SESSION_REAP_INDEX = "ix_images_upload_session_status_expires"


class UploadSession(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_upload_session"
    __table_args__ = (Index(UPLOAD_SESSION_REAP_INDEX, "status", "expires_at"),)

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id")
    image_id: uuid.UUID = Field(sa_column=Column(Uuid, nullable=False, unique=True))
    """The id the image row will get. No foreign key: the row exists only once
    the upload completes."""
    storage_key: str = Field(max_length=500)
    backend_upload_id: str = Field(max_length=500)
    size: int = Field(sa_type=BigInteger, sa_column_kwargs={"nullable": False})
    content_type: str = Field(max_length=100)
    status: UploadStatus = enum_col(UploadStatus, "upload_status", UploadStatus.OPEN)
    expires_at: datetime = Field(sa_type=AwareDateTime(), sa_column_kwargs={"nullable": False})
