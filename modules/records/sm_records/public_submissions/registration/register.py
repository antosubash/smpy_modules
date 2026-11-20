"""A visitor registers: the record and its seat in one transaction (PR 9).

Called by :func:`sm_records.public_submissions.submit.submit` after every check the form route
makes (rate limits, honeypot, the signed token, the type's budget, captcha, consent, patterns).
**The event and the occurrence come only from the verified token**; the type says which fields
are asked, the consent text and who is told; nothing the visitor sends names an event.

The order, in one transaction (the global lock order is documented in
:mod:`sm_records.public_submissions.registration.seats`):

1. what the event offers now (``describe``, a read): an event that is not public, a closed or
   cancelled occurrence refuse everyone alike (``event_unavailable``, ``registration_closed``);
2. the payload is validated, the same way for everyone, before anything is looked up;
3. the type lock, then a look for a live registration of the same address for the same occurrence:
   found, the answer is the same 202 (a pending one is mailed again within the address's budget, a
   registered one is mailed nothing), so the form is no oracle for who is registered, and the
   capacity decision below is never reached by somebody who already holds a seat;
4. otherwise the record is created (a draft, written by nobody, with its ``sm_*`` values through
   ``system=``), then ``admit`` takes the seat on the same session: a refusal (``registration_full``
   and the rest) is raised, and the route's rollback leaves no record and no seat.
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions_api import SubmitBody
from sm_records.core import events, locales
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import bound_tenant
from sm_records.models import Record, RecordStatus, RecordType, tables_for
from sm_records.public_submissions import abuse
from sm_records.public_submissions.confirmation import budget_wait
from sm_records.public_submissions.definition import (
    EMAIL_KEY,
    consent_text,
    page_locale,
)
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.registration import codes, mail, seats
from sm_records.public_submissions.registration.status import LIVE, PENDING, REGISTERED
from sm_records.public_submissions.registration.tokens import RegistrationToken
from sm_records.public_submissions.subscribe import normalise
from sm_records.public_submissions.tokens import host_secret, ip_hash
from sm_records.records.index.query import Filter, FilterOp, exists_query
from sm_records.records.services import records as record_service
from sm_records.records.services._common import SESSION_HAS_WRITES_KEY, utcnow
from sm_records.records.services._lock import lock_type
from sm_records.records.services._payload import carry_system, field_defs, validate
from sm_records.records.services.errors import Conflict, ValidationFailed
from sm_records.schema._text_checks import checked

__all__ = ["register"]

NAME_KEY = "sm_name"


def _refuse(code: str) -> SubmissionRefused:
    return SubmissionRefused(code, codes.TABLE[code].message)


def _availability_refusal(state: str) -> str | None:
    if state == "unavailable":
        return codes.EVENT_UNAVAILABLE
    if state in ("cancelled", "closed", "not_open_yet"):
        return codes.REGISTRATION_CLOSED
    if state == "full":  # the same for everyone, a registered person included
        return codes.REGISTRATION_FULL
    return None


def _fresh(
    request: Request,
    rtype: RecordType,
    body: SubmitBody,
    settings: RecordsSettings,
    token: RegistrationToken,
    avail: Any,
    email: str,
    name: str,
) -> dict[str, Any]:
    """Every system value a registration writes: a consent, a nonce, the event's facts."""
    config = rtype.public_submissions or {}
    locale = page_locale(body.locale)
    double = bool(config.get("double_opt_in", True))
    now = utcnow()
    required = bool((config.get("consent") or {}).get("required"))
    return {
        EMAIL_KEY: email,
        NAME_KEY: name,
        "sm_event_id": token.event_id,
        "sm_occurrence_key": token.occurrence_key,
        "sm_occurrence_start": avail.event.starts_at,
        "sm_event_title": avail.event.title[:300],
        "sm_status": PENDING if double else REGISTERED,
        "sm_locale": locale,
        "sm_source_page": abuse.source_page(request),
        "sm_consent_text": consent_text(config, settings, locale) if required else None,
        "sm_consent_at": now,
        "sm_confirmed_at": None if double else now,
        "sm_cancelled_at": None,
        "sm_confirm_sent_at": None,
        "sm_ip_hash": (
            ip_hash(host_secret(request.app), bound_tenant(), abuse.client_ip(request))
            if settings.public_submissions_store_ip_hash
            else None
        ),
        "sm_nonce": secrets.token_hex(16),
    }


def _check(rtype: RecordType, data: dict[str, Any], fresh: dict[str, Any], settings: Any) -> None:
    defs = field_defs(rtype)
    try:
        validate(
            rtype,
            defs,
            carry_system(defs, data, None, fresh),
            max_payload_bytes=settings.max_payload_bytes,
        )
    except ValidationFailed as exc:
        raise SubmissionRefused("invalid", exc.detail, errors=exc.errors) from exc


async def _live_registration(
    db: AsyncSession, rtype: RecordType, email: str, token: RegistrationToken
) -> Record | None:
    """The live, untrashed ``pending`` or ``registered`` record of this address for this
    occurrence, if there is one."""
    cls = tables_for(rtype).record
    tenant = bound_tenant()
    probe = exists_query(
        rtype,
        list(rtype.fields or []),
        [
            Filter(EMAIL_KEY, FilterOp.EQ, email),
            Filter("sm_event_id", FilterOp.EQ, token.event_id),
            Filter("sm_occurrence_key", FilterOp.EQ, token.occurrence_key),
        ],
    ).where(cls.tenant_id == tenant)
    ids = (await db.execute(probe)).scalars().all()
    if not ids:
        return None
    stmt = select(cls).where(cls.id.in_(ids), cls.tenant_id == tenant, cls.type_id == rtype.id)
    for record in (await db.execute(stmt)).scalars():
        if (record.data or {}).get("sm_status") in LIVE:
            return record
    return None


class _Declined(Exception):  # noqa: N818 - control flow inside the savepoint
    """The admit refused (full, closed or gone in the instant after the availability read)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def _discard(db: AsyncSession) -> None:
    await events.rollback(db)
    db.info.pop(SESSION_HAS_WRITES_KEY, None)


async def register(
    request: Request,
    db: AsyncSession,
    rtype: RecordType,
    data: dict[str, Any],
    address: Any,
    name: Any,
    token: RegistrationToken,
    body: SubmitBody,
    settings: RecordsSettings,
    verdicts: Any,
) -> None:
    """Register ``address`` for the token's occurrence; returns (to the one ``202``) whatever state
    the person is in. What actually happened is told by mail to that address, never by the answer.

    Refusals that belong to the **event** (not public, closed, cancelled, full) answer everybody
    alike before anything about the person is looked at. Past them every branch does the same
    work (the type lock, a look for the person's live registration, an admit that is idempotent for
    a holder who already has a seat) and answers the same 202."""
    tenant = bound_tenant()
    email = normalise(address)
    clean_name = name.strip() if isinstance(name, str) else ""
    lang = page_locale(body.locale) or locales.default(settings)
    integration = seats.integration()
    avail = await integration.describe(
        db,
        tenant_id=tenant,
        event_id=token.event_id,
        occurrence_key=token.occurrence_key,
        target=rtype.key,
        locale=lang,
    )
    if avail.state == "unavailable" or avail.event is None:
        # Not public, not published, not this form's: not public knowledge, so the same answer as a
        # token that does not verify or has expired. It confirms neither that the event exists nor
        # that the token was ever valid for it.
        raise SubmissionRefused("form_expired", "form token has expired; load the form again")
    if (code := _availability_refusal(avail.state)) is not None:
        raise _refuse(code)
    fresh = _fresh(request, rtype, body, settings, token, avail, email, clean_name)
    outcome: tuple[str, Record | None] = ("registration", None)
    with checked(verdicts):
        _check(rtype, data, fresh, settings)
        await lock_type(db, rtype)
        # A seat is taken at submit only where nothing later can attach it (single opt-in); on a
        # double opt-in form it is taken at the confirmation, so a submit never moves a count.
        takes_seat = fresh["sm_status"] == REGISTERED
        existing = await _live_registration(db, rtype, email, token)
        if existing is not None:
            if takes_seat:  # the same locks and reads as a new one: an idempotent admit
                await integration.admit(
                    db,
                    tenant_id=tenant,
                    event_id=token.event_id,
                    occurrence_key=token.occurrence_key,
                    target=rtype.key,
                    holder=existing.uuid,
                )
            was_pending = (existing.data or {}).get("sm_status") == PENDING
            outcome = ("registration" if was_pending else "already", existing)
        else:
            try:
                record = await record_service.create_record(
                    db,
                    rtype,
                    data=data,
                    settings=settings,
                    status=RecordStatus.DRAFT,
                    actor=None,
                    system=fresh,
                )
                if takes_seat:
                    given = await integration.admit(
                        db,
                        tenant_id=tenant,
                        event_id=token.event_id,
                        occurrence_key=token.occurrence_key,
                        target=rtype.key,
                        holder=record.uuid,
                        locale=lang,
                    )
                    if not given.admitted:
                        raise _Declined(codes.known(given.code))
                outcome = ("registration", record)
            except ValidationFailed as exc:
                raise SubmissionRefused("invalid", exc.detail, errors=exc.errors) from exc
            except Conflict as exc:
                raise SubmissionRefused("conflict", exc.detail) from exc
            except _Declined as declined:
                await _discard(db)  # nothing is stored, and nothing announces a record
                await db.refresh(rtype)  # the rollback expired it; the mail below reads it
                outcome = (codes.TABLE[declined.code].notice, None)
    kind, record = outcome
    if await budget_wait(request, rtype, email, settings) != 0:
        return  # over the address's own budget: still the one 202, nothing sent
    if record is not None:
        await mail.queue_registration_mail(db, request, rtype, record, avail.event, kind=kind)
    else:
        await mail.queue_notice_mail(db, request, rtype, email, avail.event, kind, lang)
