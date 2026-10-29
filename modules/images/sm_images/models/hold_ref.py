"""Who owns a storage-gauge hold: the arbiter between installing and releasing it.

Every hold images reserves and keeps gets a row. A hold an image names is
``installed``; one it named before a replacement, or a rehold's replacement
nobody installed, is ``orphan``; a rehold's replacement not yet installed is
``reserved``. Installing a replacement is a compare-and-set
``reserved|orphan → installed`` in the transaction that writes it onto the
image; releasing one first wins ``reserved|orphan → releasing`` and only then
calls billing (``released`` after). So a swap and a release of the same hold
can never both win (``sm_images.hold_refs``).
"""

from __future__ import annotations

import uuid

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Uuid
from sqlmodel import Field

from sm_images.models._base import Base

REF_RESERVED = "reserved"
REF_INSTALLED = "installed"
REF_ORPHAN = "orphan"
REF_RELEASING = "releasing"
REF_RELEASED = "released"


class HoldRef(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_hold_ref"

    hold_id: str = Field(primary_key=True, max_length=64)
    image_id: uuid.UUID | None = Field(default=None, sa_type=Uuid, nullable=True)
    """No foreign key: the ref outlives a purged image until its release lands."""
    state: str = Field(max_length=16)
