"""The two translation routes — a record's counterparts in other languages.

Split from :mod:`sm_records.endpoints.api.records` for the 300-line cap, along
the seam the services layer already draws: that module is CRUD on one document,
this one is the relationship between several
(:mod:`sm_records.services._translations`).

Both routes carry the same gates a record read and a record write carry: the
static permission at the router, and ``check_type_roles`` — design §10's
per-type ``allowed_roles`` narrowing — inside the handler, because it depends
on the specific ``RecordType`` the path names. Creating a translation *is*
creating a record, so ``records.manage_types`` is not a way around a type whose
records the caller may not touch.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.i18n import TranslationCreate, TranslationRead, translation_read
from sm_records.contracts.schemas import RecordRead, record_read
from sm_records.deps import (
    actor,
    check_type_roles,
    get_settings,
    load_allowed_type,
    load_type,
    request_db,
    require_edit,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.models import Record, RecordType
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings

router = APIRouter(prefix="/types/{key}", route_class=RecordsErrorRoute)


async def translations_of(
    db: AsyncSession, rtype: RecordType, record: Record
) -> list[TranslationRead]:
    """The record's whole group, as the Languages panel reads it — the record
    itself included, so the panel reads one list rather than a record plus its
    siblings."""
    siblings = await record_service.list_translations(db, rtype, record.translation_group)
    return [translation_read(sibling) for sibling in siblings]


@router.get(
    "/records/{uuid}/translations",
    response_model=list[TranslationRead],
    dependencies=[require_view],
)
async def list_record_translations(
    uuid: str,
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
) -> list[TranslationRead]:
    """Every record sharing this one's ``translation_group``, itself included.

    Trashed siblings are listed and flagged rather than hidden: a trashed
    record keeps its claim on its language until it is purged or restored, so a
    panel that dropped it would offer an "Add translation" that can only 409.
    """
    record = await record_service.get_record(db, rtype, uuid)
    return await translations_of(db, rtype, record)


@router.post(
    "/records/{uuid}/translations",
    response_model=RecordRead,
    status_code=201,
    dependencies=[require_edit],
)
async def create_record_translation(
    uuid: str,
    body: TranslationCreate,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    """Create this record's counterpart in another language (Phase 5 §4.3).

    ``records.edit`` plus ``check_type_roles`` — the type's ``allowed_roles``
    narrow this exactly as they narrow every other record write (§10); a
    translation is a record, and creating one is creating a record.
    """
    check_type_roles(request, rtype)
    source = await record_service.get_record(db, rtype, uuid)
    created = await record_service.create_translation(
        db,
        rtype,
        source,
        locale=body.locale,
        slug=body.slug,
        settings=settings,
        actor=who,
    )
    return record_read(rtype, created)


__all__ = ["router", "translations_of"]
