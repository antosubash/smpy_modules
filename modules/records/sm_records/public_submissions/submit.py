"""The submission pipeline: from an anonymous ``POST`` to a stored record (#101).

Every check runs before anything is written, cheapest first: the two rate
limits, the honeypot, the signed form token, the type (enabled, of a kind
served), whether what the visitor saw has changed, the allowlist of fields, the
consent box, and the field patterns — in a worker process, under one deadline
for the whole submission (:mod:`.patterns`). Then the write is
``services.records.create_record`` — the call the admin ``POST /records``
makes — so validation, ``unique`` claims, the revision, the index rows and
``RecordCreated`` are exactly an admin create's.
The record is always a **draft** (a submission is personal data, and never
published), written by nobody (``actor=None``), with its ``sm_*`` values
passed through ``system=``; nothing the visitor sends can reach one.

A newsletter list (``kind: "subscription"``) takes the same checks, then
branches to :mod:`.subscribe`: one record per address, with a double opt-in.

A **honeypot** hit answers the same 202 as a real submission and stores and
sends nothing — a bot learns nothing, and a false positive is invisible,
which is the accepted trade-off. A submission with too many links is
**stored as spam**: trashed, marked ``links``, nobody notified, and *Not
spam* brings it back.
"""

from __future__ import annotations

import hmac
import logging
import time
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.contracts.events import FormSubmitted
from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.contracts.public_submissions_api import SubmitBody
from sm_records.models import RecordStatus, RecordType
from sm_records.public_submissions import abuse, captcha, subscribe
from sm_records.public_submissions.definition import (
    EMAIL_KEY,
    accepting_type,
    consent_text,
    definition,
    form_digest,
    page_locale,
    public_fields_of,
)
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.mail_runner import queue_notification
from sm_records.public_submissions.patterns import check_patterns
from sm_records.public_submissions.tokens import TokenError, host_secret, ip_hash, verify_form
from sm_records.schema._text_checks import checked
from sm_records.schema.types import FieldType
from sm_records.services import records as record_service
from sm_records.services._payload import field_defs
from sm_records.services.errors import Conflict, ValidationFailed
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = ["submit", "visitor_data"]

logger = logging.getLogger(__name__)

MAX_USER_AGENT = 256


def visitor_data(rtype: RecordType, sent: dict[str, Any]) -> dict[str, Any]:
    """The visitor's values, restricted to ``public_fields``.

    A key outside the allowlist is a ``422 unknown_field`` rather than
    silently dropped: a form that sends one is out of date or forged, and
    either way it should hear so. An email address is trimmed and lowercased,
    so the same inbox is one value to filter, de-duplicate and erase by.
    Fields the visitor does not fill get their default from the validator.
    """
    allowed = {entry.key for entry in public_fields_of(rtype)}
    unknown = sorted(set(sent) - allowed)
    if unknown:
        raise SubmissionRefused(
            "unknown_field",
            f"this form has no field {unknown[0]!r}",
            errors=[{"field": key, "message": "not a field of this form"} for key in unknown],
        )
    emails = {entry.key for entry in field_defs(rtype) if entry.type is FieldType.EMAIL}
    return {
        key: value.strip().lower() if key in emails and isinstance(value, str) else value
        for key, value in sent.items()
    }


def _system(
    request: Request, rtype: RecordType, body: SubmitBody, settings: RecordsSettings, spam: bool
) -> dict[str, Any]:
    config = rtype.public_submissions or {}
    tenant = bound_tenant()
    locale = page_locale(body.locale)
    agent = request.headers.get("user-agent") or ""
    store_ip = settings.public_submissions_store_ip_hash
    store_agent = settings.public_submissions_store_user_agent
    required = bool((config.get("consent") or {}).get("required"))
    return {
        "sm_source_page": abuse.source_page(request),
        "sm_source_block": body.block or None,
        "sm_locale": locale,
        "sm_ip_hash": (
            ip_hash(host_secret(request.app), tenant, abuse.client_ip(request))
            if store_ip
            else None
        ),
        "sm_user_agent": (agent[:MAX_USER_AGENT] or None) if store_agent else None,
        "sm_consent_text": consent_text(config, settings, locale) if required else None,
        "sm_spam": "links" if spam else None,
        "sm_notified_at": None,
    }


async def _check_token(
    request: Request, db: AsyncSession, type_key: str, body: SubmitBody, settings: RecordsSettings
) -> RecordType:
    tenant = bound_tenant()
    secret = host_secret(request.app)
    try:
        token = verify_form(
            secret,
            body.token,
            tenant,
            type_key,
            min_fill=settings.public_submissions_min_fill_seconds,
            max_age=settings.public_submissions_token_max_age_seconds,
        )
    except TokenError as exc:
        raise SubmissionRefused("form_expired", f"{exc}; load the form again") from exc
    rtype = await accepting_type(db, type_key)
    if not hmac.compare_digest(token.digest, form_digest(rtype, settings, body.locale)):
        # Issued as if loaded ``min_fill`` ago: the visitor has spent that long
        # on the form already, and the resend must not be ``form_expired``.
        fresh = definition(
            rtype,
            settings,
            secret=secret,
            tenant=tenant,
            locale=body.locale,
            issued=time.time() - settings.public_submissions_min_fill_seconds,
        )
        raise SubmissionRefused(
            "form_changed",
            "this form changed after it was loaded; check it and send it again",
            definition=fresh.model_dump(mode="json"),
        )
    return rtype


async def submit(
    request: Request,
    db: AsyncSession,
    type_key: str,
    body: SubmitBody,
    settings: RecordsSettings,
) -> None:
    tenant = bound_tenant()
    ip = abuse.client_ip(request)
    await abuse.hit(
        request, abuse.rate_key(tenant, f"ip={ip}"), settings.public_submissions_rate_per_ip
    )
    if body.hp.strip():
        logger.info(
            "records.public_submissions.honeypot_dropped", extra={"type_key": type_key[:100]}
        )
        return
    rtype = await _check_token(request, db, type_key, body, settings)
    # After the token: only a form this host signed counts against the type's
    # budget, so a flood of forged posts cannot use it up (or mint a counter
    # per invented type key) and lock real visitors out.
    await abuse.hit(
        request,
        abuse.rate_key(tenant, f"type={rtype.key}"),
        settings.public_submissions_type_rate,
    )
    # After the token, so only a form this host signed costs a call to the
    # provider; before anything is read into a record or written.
    await captcha.verify(settings, body.captcha_response, ip)
    sent = dict(body.data)
    newsletter = rtype.public_submissions.get("kind") == KIND_SUBSCRIPTION
    address = sent.pop(EMAIL_KEY, None) if newsletter else None
    data = visitor_data(rtype, sent)
    if (rtype.public_submissions.get("consent") or {}).get("required") and not body.consent:
        raise SubmissionRefused(
            "consent_required",
            "tick the consent box to send this form",
            errors=[{"field": "consent", "message": "required"}],
        )
    # Off the event loop, under one deadline for the whole submission; the
    # write below validates with these verdicts instead of matching again.
    verdicts = await check_patterns(rtype, data)
    if newsletter:
        await subscribe.signup(request, db, rtype, data, address, body, settings, verdicts)
        return
    limit = settings.public_submissions_max_links
    spam = bool(limit) and abuse.count_links(data) > limit
    try:
        with checked(verdicts):
            record = await record_service.create_record(
                db,
                rtype,
                data=data,
                settings=settings,
                status=RecordStatus.DRAFT,
                actor=None,
                system=_system(request, rtype, body, settings, spam),
            )
    except ValidationFailed as exc:
        raise SubmissionRefused("invalid", exc.detail, errors=exc.errors) from exc
    except Conflict as exc:
        raise SubmissionRefused("conflict", exc.detail) from exc
    if spam:
        await record_service.soft_delete_record(db, rtype, record, settings=settings)
    else:
        await queue_notification(db, request.app, rtype, record)
    events.emit(
        db,
        FormSubmitted(type_key=rtype.key, tenant_id=rtype.tenant_id, uuid=record.uuid, spam=spam),
    )
