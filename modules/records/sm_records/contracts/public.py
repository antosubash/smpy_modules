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

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.constants import ORPHANED_KEY
from sm_records.contracts.i18n import PublicTranslationRead, public_translation_read
from sm_records.models import Record, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services._payload import field_defs, read_view

__all__ = ["PublicRecordPage", "PublicRecordRead", "public_record_read", "public_records_read"]


class PublicRecordRead(SQLModel):
    uuid: str
    slug: str | None
    locale: str
    """Which language this record is written in — the one thing a site needs
    besides the payload to render it under the right ``lang`` attribute."""
    display_title: str
    published_at: datetime | None
    data: dict[str, Any]
    translations: list[PublicTranslationRead] = SQLField(default_factory=list)
    """The record's **published, live** siblings, so a site can render a
    language switcher (Phase 5 §4.4).

    Published only, never the trash, and never a locale the install has since
    dropped from ``content_locales``: advertising any of the three would point
    a reader — and a crawler — at a 404, because none of them is served here.
    Resolved in one batched query per page, keyed by ``translation_group`` and
    never per row (``services._translations.published_siblings``).

    ``translation_group`` itself is *not* published: it is an internal
    grouping key, and a reader needs the addresses, not the join column."""


class PublicRecordPage(SQLModel):
    """The anonymous listing's page shape — :class:`RecordPage`'s public twin,
    with the same ``total``/``total_capped``/``next_cursor`` contract (F4, F11)
    and the same defaults, so an existing reader is unaffected."""

    items: list[PublicRecordRead]
    total: int | None
    page: int
    page_size: int
    total_capped: bool = False
    next_cursor: str | None = None
    media_url_template: str | None = None
    """How to render a ``media`` value on a public page: a URL with ``{id}`` in
    it when the host's media library serves files to anonymous callers, and
    ``null`` otherwise — which, with the framework ``file_storage`` module, is
    always: it exempts none of its routes from authentication
    (:mod:`sm_records.media`). ``null`` means "do not try": a stored id is not
    a URL a visitor can load."""


def public_record_read(
    rtype: RecordType,
    record: Record,
    *,
    defs: list[FieldDefinition] | None = None,
    siblings: list[Record] | None = None,
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
        locale=record.locale,
        display_title=record.display_title,
        published_at=record.published_at,
        data=data,
        translations=[public_translation_read(sibling) for sibling in siblings or []],
    )


def public_records_read(
    rtype: RecordType,
    records: list[Record],
    *,
    siblings: dict[str, list[Record]] | None = None,
) -> list[PublicRecordRead]:
    """A page, with the type's field definitions validated once, not per row.

    ``siblings`` is the whole page's translation groups, already resolved —
    what ``services._translations.published_siblings`` returns. *Looked up*
    here rather than queried, for the reason §9 gives about expansion: one
    batched query per page is the rule, and a per-row query hiding behind this
    signature would be exactly the regression it exists to prevent.
    """
    defs = field_defs(rtype)
    return [
        public_record_read(
            rtype,
            record,
            defs=defs,
            siblings=None if siblings is None else siblings.get(record.translation_group),
        )
        for record in records
    ]
