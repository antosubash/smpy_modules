"""``/api/records/registrations/mine``: a signed-in person's own registrations (PR 9).

Not behind ``records.view``: the list is the caller's, not the type's. It is matched on the
caller's **verified** address, read from the framework's account directory (never from the request
or the session's copy), and bound to the resolved tenant like every records route: an account
whose address the directory does not report as verified (or reports as nothing) gets an empty
answer, the same shape as one with no registrations, so there is no way to learn which addresses
registered. Only ``pending`` and ``registered`` upcoming registrations are listed, never an
address, a name or another person's row. Cancelling is the same cancel the registrant's mail link
does, so the seat goes in the same transaction; anything that is not the caller's own is a 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from simple_module_core.user_directory import get_user_directory
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import bound_tenant
from sm_records.models import Record, RecordType, tables_for
from sm_records.public_submissions.registration import cancel as cancelling
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.registration import start as start_module
from sm_records.public_submissions.registration.status import LIVE
from sm_records.public_submissions.subscribe import normalise
from sm_records.records.index.query import Filter, FilterOp, filtered
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow
from sm_records.records.services.errors import NotFound
from sm_records.web.deps import get_settings, request_db
from sm_records.web.endpoints.api._errors import RecordsErrorRoute
from sm_records.web.endpoints.api._responses import TYPE_WRITE, responses

__all__ = ["router"]

EMAIL_KEY = "sm_email"
MAX_ITEMS = 100
NOT_FOUND = "registration not found"


class MineItem(SQLModel):
    uuid: str
    type_key: str
    status: str
    event_id: str
    occurrence_key: str
    title: str
    when_text: str | None = None
    page_path: str | None = None
    starts_at: str | None = None


class MineOut(SQLModel):
    verified: bool
    items: list[MineItem]


def signed_in(request: Request) -> str:
    """The caller's id; a request with no account is a 401 (these routes have no permission of
    their own: the list is the caller's, whoever they are)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return str(user.id)


router = APIRouter(
    route_class=RecordsErrorRoute,
    dependencies=[Depends(signed_in)],
    responses=responses(*TYPE_WRITE),
)


async def verified_address(request: Request, db: AsyncSession) -> str | None:
    """The caller's address when the directory proves it (active and ``email_verified``)."""
    who = signed_in(request)
    found = (await get_user_directory(request.app).get_many(db, [who])).get(who)
    if found is None or not found.is_active or found.email_verified is not True:
        return None
    try:
        return normalise(found.email)
    except (ValueError, TypeError):
        return None


async def _own(db: AsyncSession, email: str) -> list[tuple[RecordType, Record]]:
    """The caller's live, untrashed registrations in the bound tenant (the upcoming ones are picked
    in :func:`_items`, from events' resolved start)."""
    tenant = bound_tenant()
    out: list[tuple[RecordType, Record]] = []
    for rtype in await type_service.list_types(db):
        if (rtype.public_submissions or {}).get("kind") != KIND_REGISTRATION:
            continue
        cls = tables_for(rtype).record
        stmt = filtered(
            select(cls).where(cls.type_id == rtype.id, cls.tenant_id == tenant),
            rtype,
            list(rtype.fields or []),
            [Filter(EMAIL_KEY, FilterOp.EQ, email)],
        ).limit(MAX_ITEMS)
        for record in (await db.execute(stmt)).scalars():
            data = record.data or {}
            if not record.is_deleted and data.get("sm_status") in LIVE:
                out.append((rtype, record))
    return out


def _title(record: Record, facts: Any) -> tuple[str, str | None, str | None]:
    data = record.data or {}
    if facts is not None:
        return facts.title, facts.when_text, facts.page_path
    return str(data.get("sm_event_title") or ""), None, None  # the snapshot, when events cannot say


async def _items(
    db: AsyncSession, own: list[tuple[RecordType, Record]], locale: str, now: datetime
) -> list[MineItem]:
    starts = await start_module.resolve_many(db, bound_tenant(), [r.data or {} for _, r in own])
    own = [pair for pair, begun in zip(own, starts, strict=True) if begun is None or begun > now]
    own = own[:MAX_ITEMS]
    facts: dict[tuple[uuid.UUID, str], Any] = {}
    if own and seats.available():
        refs = list(
            {
                (uuid.UUID(str(r.data["sm_event_id"])), str(r.data["sm_occurrence_key"]))
                for _, r in own
                if (r.data or {}).get("sm_event_id")
            }
        )
        facts = await seats.integration().summaries(
            db, tenant_id=bound_tenant(), refs=refs, locale=locale
        )
    items = []
    for rtype, record in own:
        data = record.data or {}
        ref = (uuid.UUID(str(data["sm_event_id"])), str(data.get("sm_occurrence_key")))
        title, when_text, page_path = _title(record, facts.get(ref))
        start = data.get("sm_occurrence_start")
        items.append(
            MineItem(
                uuid=record.uuid,
                type_key=rtype.key,
                status=str(data.get("sm_status")),
                event_id=str(data.get("sm_event_id")),
                occurrence_key=str(data.get("sm_occurrence_key")),
                title=title,
                when_text=when_text,
                page_path=page_path,
                starts_at=start if isinstance(start, str) else None,
            )
        )
    items.sort(key=lambda i: (i.starts_at or "", i.uuid))
    return items


@router.get("/registrations/mine", response_model=MineOut)
async def mine(request: Request, db: AsyncSession = Depends(request_db)) -> MineOut:
    email = await verified_address(request, db)
    if email is None:
        return MineOut(verified=False, items=[])
    locale = (request.headers.get("accept-language") or "en")[:2].lower()
    return MineOut(verified=True, items=await _items(db, await _own(db, email), locale, utcnow()))


@router.post("/registrations/mine/{record_uuid}/cancel", response_model=MineOut)
async def cancel_mine(
    record_uuid: str,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
) -> MineOut:
    email = await verified_address(request, db)
    if email is None:
        raise NotFound(NOT_FOUND)
    own = await _own(db, email)
    found = next(((t, r) for t, r in own if r.uuid == record_uuid.replace("-", "").lower()), None)
    if found is None:
        raise NotFound(NOT_FOUND)
    if not await cancelling.cancel(db, found[0], found[1], settings=settings):
        raise NotFound(NOT_FOUND)
    remaining = [pair for pair in own if pair[1].uuid != found[1].uuid]
    locale = (request.headers.get("accept-language") or "en")[:2].lower()
    return MineOut(verified=True, items=await _items(db, remaining, locale, utcnow()))
