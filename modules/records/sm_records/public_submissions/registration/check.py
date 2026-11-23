"""The registration submit's token check: the form token's checks, for the event-bound token."""

from __future__ import annotations

import hmac
import time

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.contracts.public_submissions_api import SubmitBody
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import bound_tenant
from sm_records.models import RecordType
from sm_records.public_submissions.definition import form_digest, registration_definition
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.registration.tokens import (
    RegistrationToken,
    verify_registration,
)
from sm_records.public_submissions.tokens import TokenError, host_secret
from sm_records.records.services.errors import NotFound
from sm_records.records.services.public import NOT_FOUND
from sm_records.records.services.types import get_type

__all__ = ["check_token", "is_registration_token"]

_PARTS = 6


def is_registration_token(token: object) -> bool:
    """Six dot-separated parts: the shape alone picks the branch, the MAC decides everything."""
    return isinstance(token, str) and token.count(".") == _PARTS - 1


async def check_token(
    request: Request, db: AsyncSession, type_key: str, body: SubmitBody, settings: RecordsSettings
) -> tuple[RecordType, RegistrationToken]:
    """The type and the verified token. A token that does not verify (another tenant's, type's,
    purpose's or age) is ``form_expired``; an unknown type, a type of another kind or no events
    module is the shared 404; a switched-off type is ``registration_closed``; a form that changed
    since it was loaded is ``form_changed``."""
    tenant = bound_tenant()
    secret = host_secret(request.app)
    try:
        token = verify_registration(
            secret,
            body.token,
            tenant,
            type_key,
            min_fill=settings.public_submissions_min_fill_seconds,
            max_age=settings.public_submissions_token_max_age_seconds,
        )
    except TokenError as exc:
        raise SubmissionRefused("form_expired", f"{exc}; load the form again") from exc
    try:
        rtype = await get_type(db, type_key)
    except NotFound:
        raise NotFound(NOT_FOUND) from None
    config = rtype.public_submissions or {}
    if config.get("kind") != KIND_REGISTRATION or not seats.available():
        raise NotFound(NOT_FOUND)
    if not config.get("enabled"):
        raise SubmissionRefused("registration_closed", "registration is closed")
    if not hmac.compare_digest(token.digest, form_digest(rtype, settings, body.locale)):
        fresh = registration_definition(
            rtype,
            settings,
            secret=secret,
            tenant=tenant,
            locale=body.locale,
            event_id=token.event_id,
            occurrence_key=token.occurrence_key,
            issued=time.time() - settings.public_submissions_min_fill_seconds,
        )
        raise SubmissionRefused(
            "form_changed",
            "this form changed after it was loaded; check it and send it again",
            definition=fresh.model_dump(mode="json"),
        )
    return rtype, token
