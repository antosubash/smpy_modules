"""Admin actions on a website submission (#101): resend, spam, not spam — and
on a newsletter list, resend the confirmation and unsubscribe.

Included in the admin ``router`` (``endpoints.api``), so the tenant binding
and the CSRF check come first; every route here also needs ``records.edit``
and passes the type's ``allowed_roles``. Registered **before** ``records``
for the path-shadowing reason that module's mount point documents. The work
is :mod:`sm_records.public_submissions.actions`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions_api import NotificationQueued
from sm_records.contracts.schemas import RecordRead, record_read
from sm_records.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_type,
    request_db,
    require_edit,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.endpoints.api._responses import SUBMISSION_ACTION, responses
from sm_records.models import RecordType
from sm_records.public_submissions import actions
from sm_records.services import records as record_service
from sm_records.settings import RecordsSettings

__all__ = ["router"]

router = APIRouter(
    prefix="/types/{key}/records/{uuid}/submission",
    route_class=RecordsErrorRoute,
    responses=responses(*SUBMISSION_ACTION),
    dependencies=[require_edit],
)


@router.post("/resend", status_code=202, response_model=NotificationQueued)
async def resend_notification(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> NotificationQueued:
    """Send the submission's notification again (at most once a minute), or a
    pending newsletter subscriber's confirmation (within the address's
    budget)."""
    check_type_roles(request, rtype)
    record = await record_service.get_record(db, rtype, uuid)
    await actions.resend(db, request.app, request, rtype, record)
    return NotificationQueued()


@router.post("/spam", response_model=RecordRead)
async def mark_spam(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    """Mark as spam (``sm_spam="manual"``) and move to the trash."""
    check_type_roles(request, rtype)
    actions.require_form(rtype)
    record = await record_service.get_record(db, rtype, uuid)
    record = await actions.mark_spam(
        db, rtype, record, settings=settings, actor=who, roles=caller_roles(request)
    )
    return record_read(rtype, record)


@router.post("/not-spam", response_model=RecordRead)
async def mark_not_spam(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> RecordRead:
    """Restore from the trash, clear ``sm_spam`` and send the notification."""
    check_type_roles(request, rtype)
    actions.require_form(rtype)
    record = await record_service.get_deleted_record(db, rtype, uuid)
    record = await actions.mark_not_spam(
        db, request.app, rtype, record, settings=settings, actor=who
    )
    return record_read(rtype, record)


@router.post("/unsubscribe", response_model=RecordRead)
async def unsubscribe_subscriber(
    uuid: str,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> RecordRead:
    """Unsubscribe a newsletter subscriber: the suppression record stays, the
    consent proof goes, and every link sent before stops working."""
    check_type_roles(request, rtype)
    actions.require_subscription(rtype)
    record = await record_service.get_record(db, rtype, uuid)
    record = await actions.unsubscribe(db, rtype, record, settings=settings)
    return record_read(rtype, record)
