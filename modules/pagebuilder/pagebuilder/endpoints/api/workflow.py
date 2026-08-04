"""Status-transition endpoints: publish, unpublish, submit, approve, reject, schedule."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    PageNoteRequest,
    PageRead,
    PageRejectRequest,
    PageScheduleRequest,
)
from pagebuilder.endpoints.api._deps import require_approve, require_edit, require_publish
from pagebuilder.service import _UNSET, PagesService

router = APIRouter()


def _note(body: PageNoteRequest | None) -> str | None:
    return body.note if body else None


@router.post(
    "/pages/{page_id}/publish",
    response_model=PageRead,
    dependencies=[require_publish],
)
async def publish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Publish the current draft. The optional ``note`` is captured on
    the revision row so the history panel can label the publish."""
    page = await PagesService(db).publish(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/unpublish",
    response_model=PageRead,
    dependencies=[require_publish],
)
async def unpublish_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    page = await PagesService(db).unpublish(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/submit",
    response_model=PageRead,
    dependencies=[require_edit],
)
async def submit_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Editor action: hand a draft off to the approver queue."""
    page = await PagesService(db).submit_for_review(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/approve",
    response_model=PageRead,
    dependencies=[require_approve],
)
async def approve_page(
    page_id: int,
    db: AsyncSession = Depends(get_db),
    body: PageNoteRequest | None = None,
) -> PageRead:
    """Approver action: take a submission live (also publishes)."""
    page = await PagesService(db).approve(page_id, note=_note(body))
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/schedule",
    response_model=PageRead,
    dependencies=[require_publish],
)
async def schedule_page(
    page_id: int,
    body: PageScheduleRequest,
    db: AsyncSession = Depends(get_db),
) -> PageRead:
    """Set or clear scheduled flip timestamps.

    Each field uses ``model_fields_set`` to distinguish "field absent"
    (leave the existing value alone) from ``"field": null`` (clear). So
    ``POST {"publish_at": "..."}`` only touches ``publish_at`` and leaves
    ``unpublish_at`` as-is.
    """
    publish_at = body.publish_at if "publish_at" in body.model_fields_set else _UNSET
    unpublish_at = body.unpublish_at if "unpublish_at" in body.model_fields_set else _UNSET
    page = await PagesService(db).schedule(
        page_id,
        publish_at=publish_at,
        unpublish_at=unpublish_at,
    )
    return PageRead.model_validate(page)


@router.post(
    "/pages/{page_id}/reject",
    response_model=PageRead,
    dependencies=[require_approve],
)
async def reject_page(
    page_id: int,
    body: PageRejectRequest,
    db: AsyncSession = Depends(get_db),
) -> PageRead:
    """Approver action: send a submission back to draft with feedback."""
    page = await PagesService(db).reject(page_id, body.note)
    return PageRead.model_validate(page)
