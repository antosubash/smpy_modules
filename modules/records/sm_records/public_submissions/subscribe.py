"""A newsletter signup: one record per address, double opt-in (#101, §7.1).

The address (``sm_email``, trimmed and lowercased) is looked up on its index,
the trash included, and the record's state decides what happens:

=================  ==========================================  ================
State              Write                                       Mail
=================  ==========================================  ================
none               a new record: ``pending`` (``confirmed``     confirmation
                   without double opt-in), consent, a nonce
``pending``        none                                        confirmation again
``confirmed``      none                                        **none**
``unsubscribed``   back to ``pending``, new consent, a          confirmation
                   **rotated** nonce (its old links die)
in the trash       restored, then as ``unsubscribed``           confirmation
=================  ==========================================  ================

Without double opt-in only a **new** address is confirmed at once: one the
list has seen (unsubscribed, trashed, still pending) takes the pending path
and its confirmation, so nobody can re-subscribe someone who left.

**Every branch answers the same 202**, and everything that can refuse — the
address and the visitor's other values, against the schema — is checked
*before* the lookup, the same way for every state, so no answer depends on
whether an address is on the list. Mail is never sent in the request, so its
latency is no tell either; what remains is one write against none, which the
rate limits bound. A confirmed subscriber is never mailed by a signup — the
form cannot be used to send anyone's inbox anything once they are on the
list — and a confirmation counts against the address's own budget
(``public_submissions_confirm_rate_per_email``): over it, still 202, nothing
sent.

Two signups of one address at once: the second loses ``unique``'s check
under the type lock, and its ``Conflict`` is the same 202 with nothing
written.
"""

from __future__ import annotations

import secrets
from typing import Any, Final

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.events import SubscriptionChanged
from sm_records.contracts.public_submissions_api import SubmitBody
from sm_records.index.query import Filter, FilterOp, exists_query
from sm_records.models import Record, RecordStatus, RecordType, tables_for
from sm_records.public_submissions import abuse
from sm_records.public_submissions.confirmation import queue_confirmation, within_budget
from sm_records.public_submissions.definition import EMAIL_KEY, consent_text, page_locale
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.tokens import host_secret, ip_hash
from sm_records.public_submissions.transition import Change, transition
from sm_records.schema._text_checks import checked
from sm_records.services import records as record_service
from sm_records.services._common import SESSION_HAS_WRITES_KEY, utcnow
from sm_records.services._payload import carry_system, field_defs, validate
from sm_records.services.errors import Conflict, NotFound, ValidationFailed
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = ["CONFIRMED", "PENDING", "UNSUBSCRIBED", "changed", "find", "normalise", "signup"]

PENDING: Final = "pending"
CONFIRMED: Final = "confirmed"
UNSUBSCRIBED: Final = "unsubscribed"


def normalise(value: Any) -> str:
    """One inbox, one spelling. Anything but a string is no address at all."""
    return value.strip().lower() if isinstance(value, str) else ""


def changed(rtype: RecordType, record: Record, before: str | None, after: str) -> Any:
    return SubscriptionChanged(
        type_key=rtype.key,
        tenant_id=rtype.tenant_id,
        uuid=record.uuid,
        status_before=before,
        status_after=after,
    )


def _fresh(
    request: Request, rtype: RecordType, body: SubmitBody, settings: RecordsSettings, email: str
) -> dict[str, Any]:
    """Every system value a signup writes: a new consent and a new nonce."""
    config = rtype.public_submissions or {}
    locale = page_locale(body.locale)
    double = bool(config.get("double_opt_in", True))
    now = utcnow()
    store_ip = settings.public_submissions_store_ip_hash
    required = bool((config.get("consent") or {}).get("required"))
    return {
        EMAIL_KEY: email,
        "sm_status": PENDING if double else CONFIRMED,
        "sm_locale": locale,
        "sm_source_page": abuse.source_page(request),
        "sm_consent_text": consent_text(config, settings, locale) if required else None,
        "sm_consent_at": now,
        "sm_confirmed_at": None if double else now,
        "sm_unsubscribed_at": None,
        "sm_confirm_sent_at": None,
        "sm_consent_ip_hash": (
            ip_hash(host_secret(request.app), bound_tenant(), abuse.client_ip(request))
            if store_ip
            else None
        ),
        "sm_nonce": secrets.token_hex(16),
    }


def _check(rtype: RecordType, data: dict[str, Any], fresh: dict[str, Any], settings: Any) -> None:
    """The schema's verdict on what a new record would hold — the same for
    every state, so a ``422`` says nothing about the list."""
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


async def find(db: AsyncSession, rtype: RecordType, email: str) -> Record | None:
    """The record holding ``email``, in the trash or not."""
    cls = tables_for(rtype).record
    tenant = bound_tenant()
    probe = exists_query(rtype, list(rtype.fields or []), [Filter(EMAIL_KEY, FilterOp.EQ, email)])
    probe = probe.where(cls.tenant_id == tenant).execution_options(include_deleted=True)
    found = (await db.execute(probe)).scalars().first()
    if found is None:
        return None
    stmt = select(cls).where(cls.id == found, cls.tenant_id == tenant, cls.type_id == rtype.id)
    return (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()


async def _write(
    db: AsyncSession,
    rtype: RecordType,
    existing: Record | None,
    data: dict[str, Any],
    fresh: dict[str, Any],
    settings: RecordsSettings,
) -> tuple[Record, str | None, bool]:
    """The state machine's write: ``(record, status before, wrote)``.

    An address the list has seen before goes back to ``pending`` — never
    straight to ``confirmed``, even without double opt-in: somebody who
    unsubscribed must confirm again themselves, so an anonymous signup can
    never put them back on the list. The change is decided from the row as
    it is when the write lands (:mod:`.transition`)."""
    if existing is None:
        record = await record_service.create_record(
            db, rtype, data=data, settings=settings, status=RecordStatus.DRAFT, system=fresh
        )
        return record, None, True
    restored = existing.is_deleted
    if restored:
        existing = await record_service.restore_record(db, rtype, existing, settings=settings)
    again = {**fresh, "sm_status": PENDING, "sm_confirmed_at": None}

    def derive(row: Record) -> Change | None:
        status = (row.data or {}).get("sm_status")
        if not restored and status in (PENDING, CONFIRMED):
            return None  # pending: the confirmation goes out again; confirmed: nothing
        return again, data

    outcome = await transition(db, rtype, existing, derive, settings=settings)
    before = outcome.before.get("sm_status")
    return outcome.record, before, outcome.wrote


async def _discard(db: AsyncSession) -> None:
    await events.rollback(db)
    db.info.pop(SESSION_HAS_WRITES_KEY, None)


async def signup(
    request: Request,
    db: AsyncSession,
    rtype: RecordType,
    data: dict[str, Any],
    address: Any,
    body: SubmitBody,
    settings: RecordsSettings,
    verdicts: Any,
) -> None:
    """Run the signup for ``address``; returns (to a ``202``) in every state."""
    email = normalise(address)
    fresh = _fresh(request, rtype, body, settings, email)
    with checked(verdicts):
        _check(rtype, data, fresh, settings)
        existing = await find(db, rtype, email)
        try:
            record, before, wrote = await _write(db, rtype, existing, data, fresh, settings)
        except (Conflict, NotFound):
            await _discard(db)  # a concurrent signup or admin edit of the address won
            return
    after = (record.data or {}).get("sm_status")
    if wrote:
        events.emit(db, changed(rtype, record, before, after))
    if after == PENDING and await within_budget(request, rtype, email, settings):
        await queue_confirmation(db, request.app, rtype, record)
