"""The form a website renders for a type, and the type behind it (#101).

The **type is the trust anchor**: which fields a visitor may fill, their
validation, the consent text and the recipients all live on
``RecordType.public_submissions``. A page block only names the type key, so
nothing the server relies on ships inside page JSON. The definition is fetched
live on every form mount, never from cached page JSON — an edited label or a
newly ticked field shows on the next page view.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import locales
from sm_records.constants import LOCALE_PATTERN
from sm_records.contracts.public_submissions import KIND_FORM
from sm_records.contracts.public_submissions_api import (
    SubmissionConsent,
    SubmissionDefinition,
    SubmissionField,
)
from sm_records.models import RecordType
from sm_records.public_submissions.tokens import sign_form
from sm_records.services._payload import field_defs
from sm_records.services.errors import NotFound
from sm_records.services.public import NOT_FOUND
from sm_records.services.types import get_type
from sm_records.settings import RecordsSettings

__all__ = ["accepting_type", "consent_text", "definition", "form_digest", "page_locale"]

_LOCALE_RE = re.compile(LOCALE_PATTERN)
DIGEST_LEN = 16

ACCEPTED_KINDS = frozenset({KIND_FORM})
"""The kinds the public routes serve today. A newsletter list's signup flow
(double opt-in) is not built yet, so its type answers the shared 404 here
until it is."""


async def accepting_type(db: AsyncSession, type_key: str) -> RecordType:
    """The type, if it accepts submissions right now; else the shared 404 —
    the same answer for an unknown key, a type without the config, one that
    is switched off and a kind not served yet, so the route is no oracle."""
    try:
        rtype = await get_type(db, type_key)
    except NotFound:
        raise NotFound(NOT_FOUND) from None
    config = rtype.public_submissions or {}
    if not config.get("enabled") or config.get("kind") not in ACCEPTED_KINDS:
        raise NotFound(NOT_FOUND)
    return rtype


def page_locale(value: str | None) -> str | None:
    """The page language a form reports, if it is a well-formed tag."""
    if not value:
        return None
    lowered = value.strip().lower()
    return lowered if _LOCALE_RE.match(lowered) else None


def consent_text(config: dict[str, Any], settings: RecordsSettings, locale: str | None) -> str:
    """The consent text in ``locale``, else the default content locale's,
    else any — the one a visitor sees and the one snapshotted with them."""
    texts = (config.get("consent") or {}).get("text") or {}
    for candidate in (locale, locales.default(settings)):
        if candidate and texts.get(candidate):
            return texts[candidate]
    return next((text for text in texts.values() if text), "")


def _field(entry: Any) -> SubmissionField:
    return SubmissionField(
        key=entry.key,
        type=entry.type.value,
        label=entry.label,
        help=entry.help,
        required=entry.required,
        choices=list((entry.options or {}).get("choices") or []),
        constraints=dict(entry.constraints or {}),
        default=entry.default,
    )


def _shown(
    rtype: RecordType, settings: RecordsSettings, locale: str | None
) -> tuple[list[SubmissionField], SubmissionConsent | None]:
    config = rtype.public_submissions or {}
    by_key = {entry.key: entry for entry in field_defs(rtype) if not entry.system}
    fields = [_field(by_key[key]) for key in config.get("public_fields", []) if key in by_key]
    consent_cfg = config.get("consent") or {}
    text = consent_text(config, settings, page_locale(locale))
    consent = (
        SubmissionConsent(required=bool(consent_cfg.get("required")), text=text)
        if consent_cfg.get("required") or text
        else None
    )
    return fields, consent


def _digest(
    rtype: RecordType, fields: list[SubmissionField], consent: SubmissionConsent | None
) -> str:
    shown = {
        "schema_version": rtype.schema_version,
        "fields": [entry.model_dump(mode="json") for entry in fields],
        "consent": consent.model_dump(mode="json") if consent else None,
    }
    raw = json.dumps(shown, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:DIGEST_LEN]


def form_digest(rtype: RecordType, settings: RecordsSettings, locale: str | None) -> str:
    """A digest of everything the visitor is shown in ``locale``: the schema
    version, every public field as rendered, and the consent box with its
    text. The form token carries it, so a form loaded before *any* of that
    changed -- a reworded consent text included, which bumps no schema
    version -- is ``form_changed`` rather than consent to words never seen."""
    fields, consent = _shown(rtype, settings, locale)
    return _digest(rtype, fields, consent)


def definition(
    rtype: RecordType,
    settings: RecordsSettings,
    *,
    secret: str,
    tenant: str,
    locale: str | None,
    issued: float | None = None,
) -> SubmissionDefinition:
    fields, consent = _shown(rtype, settings, locale)
    digest = _digest(rtype, fields, consent)
    return SubmissionDefinition(
        kind=(rtype.public_submissions or {})["kind"],
        schema_version=rtype.schema_version,
        fields=fields,
        consent=consent,
        token=sign_form(secret, tenant, rtype.key, digest, now=issued),
    )
