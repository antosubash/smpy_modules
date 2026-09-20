"""The anonymous read shape (design doc §10 "Public read API", Phase 4).

Fields are *removed from the shape*, not filtered from the query: an anonymous
caller sees ``uuid``, ``slug``, ``display_title``, ``published_at`` and the
payload, and nothing else — no audit columns, no ``version``, no ``status``
(everything served here is published, so the field would only ever say so),
no ``invalid``, no ``expanded`` (§10: no ``?expand=`` for anonymous callers).

``data`` is the same lenient read the admin gets (``read_view`` fills
defaults) with the reserved ``_orphaned`` sub-key stripped: a deleted field's
retained values are the admin's undo buffer, never public content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

from sm_records.constants import ORPHANED_KEY
from sm_records.models import Record, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services._payload import field_defs, read_view

__all__ = ["PublicRecordPage", "PublicRecordRead", "public_record_read", "public_records_read"]


class PublicRecordRead(SQLModel):
    uuid: str
    slug: str | None
    display_title: str
    published_at: datetime | None
    data: dict[str, Any]


class PublicRecordPage(SQLModel):
    items: list[PublicRecordRead]
    total: int
    page: int
    page_size: int


def public_record_read(
    rtype: RecordType, record: Record, *, defs: list[FieldDefinition] | None = None
) -> PublicRecordRead:
    """One published record for an anonymous reader.

    Never validates (``with_invalid=False``): the badge is the editor's, and
    a row a forced schema change marked invalid is still the published content
    the site shows until someone fixes it (§8.3 — marked, not hidden).
    """
    view = read_view(rtype, record, with_invalid=False, defs=defs)
    data = {k: v for k, v in view["data"].items() if k != ORPHANED_KEY}
    return PublicRecordRead(
        uuid=record.uuid,
        slug=record.slug,
        display_title=record.display_title,
        published_at=record.published_at,
        data=data,
    )


def public_records_read(rtype: RecordType, records: list[Record]) -> list[PublicRecordRead]:
    """A page, with the type's field definitions validated once, not per row."""
    defs = field_defs(rtype)
    return [public_record_read(rtype, record, defs=defs) for record in records]
