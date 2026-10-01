"""Content-i18n DTOs — a record's language and its siblings (Phase 5 §4).

A translation is a whole sibling record, never a per-field overlay: same
type, same ``translation_group``, its own ``uuid``, its own slug **in its own
locale**, its own status. That is pagebuilder's and news' model and it is what
keeps every slug lookup, claim and public read locale-scoped — the
half-version the original design warned about is a record with a locale
whose slug is not scoped to it.

A record's language is fixed for its lifetime: there is no ``locale`` on
``RecordUpdate``, only on create and on :class:`TranslationCreate`.
"""

from __future__ import annotations

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.models import Record

__all__ = [
    "PublicTranslationRead",
    "TranslationCreate",
    "TranslationRead",
    "public_translation_read",
    "translation_read",
]


class TranslationRead(SQLModel):
    """One sibling in the record's translation group, as the editor's
    Languages panel lists it. The record itself is included, so the panel
    reads one list rather than the record plus its siblings."""

    locale: str
    uuid: str
    status: str
    display_title: str
    is_deleted: bool = False
    """A trashed sibling is still a sibling: it keeps its slug claim in its
    locale, so the panel must show it rather than offer to create a second
    translation that would then collide."""


class TranslationCreate(SQLModel):
    """``POST /records/{uuid}/translations``. The new record copies the
    source's payload and position, starts as ``draft`` whatever the source's
    status, and gets a slug regenerated in the target locale — never the
    source's slug, which belongs to another language's namespace."""

    locale: str
    slug: str | None = SQLField(default=None, max_length=200)
    """Optional explicit slug; refused if taken in the target locale."""


class PublicTranslationRead(SQLModel):
    """What the anonymous read API lists for a language switcher: published
    siblings only, by locale, with the slug a site needs to link them."""

    locale: str
    uuid: str
    slug: str | None


def translation_read(record: Record) -> TranslationRead:
    return TranslationRead(
        locale=record.locale,
        uuid=record.uuid,
        status=record.status.value,
        display_title=record.display_title,
        is_deleted=record.is_deleted,
    )


def public_translation_read(record: Record) -> PublicTranslationRead:
    return PublicTranslationRead(locale=record.locale, uuid=record.uuid, slug=record.slug)
