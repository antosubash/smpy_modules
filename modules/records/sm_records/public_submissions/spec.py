"""The canonical system fields of each submission kind, and their injection.

A type that accepts public submissions carries ``sm_*`` fields beside its
ordinary ones: where a submission came from, its consent proof, a newsletter
address's status. They are part of ``RecordType.fields`` — so they validate,
index, filter, list and export like any field — but nobody edits their
definitions. :func:`inject` is run by ``services._schema.normalise``, the one
path every type create, update, rollback, import and preview takes: it drops
every inbound entry that claims to be a system field and appends the canonical
definitions for the type's kind. A client therefore cannot add, retype,
relabel, make optional or remove a system field, and a rollback to a revision
from before the type gained its kind still ends up with them.

Their *values* are written only through the internal ``system=`` argument of
``services.records.create_record``/``update_record``; every other write carries
the stored ones over (``services._payload.carry_system``).

``system`` is ``"readonly"`` (shown in the record editor's read-only panel, the
list's columns and the export) or ``"internal"`` (hidden
from all three, kept in the admin API's ``data``): a newsletter's
``sm_nonce`` and a contact form's ``sm_delivery``.
"""

from __future__ import annotations

import copy
from typing import Any, Final

from sm_records.contracts.public_submissions import KIND_FORM, KIND_SUBSCRIPTION
from sm_records.schema.types import FieldType

__all__ = [
    "INTERNAL",
    "READONLY",
    "SUBMITTABLE_TYPES",
    "inject",
    "is_system",
    "system_fields",
]

READONLY: Final = "readonly"
INTERNAL: Final = "internal"

SUBMITTABLE_TYPES: Final = frozenset(
    {
        FieldType.TEXT,
        FieldType.LONGTEXT,
        FieldType.EMAIL,
        FieldType.URL,
        FieldType.NUMBER,
        FieldType.INTEGER,
        FieldType.BOOLEAN,
        FieldType.DATE,
        FieldType.DATETIME,
        FieldType.SELECT,
        FieldType.MULTISELECT,
    }
)
"""What a visitor may fill in. ``relation``, ``json`` and ``media`` are never
publicly submittable: a picker needs a session, and an upload is out of scope."""


def _field(
    key: str,
    label: str,
    field_type: FieldType,
    *,
    system: str = READONLY,
    max_length: int | None = None,
    choices: tuple[str, ...] = (),
    **flags: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": field_type.value,
        "label": label,
        "required": flags.get("required", False),
        "unique": flags.get("unique", False),
        "indexed": flags.get("indexed", False),
        "default": None,
        "help": None,
        "constraints": {} if max_length is None else {"max_length": max_length},
        "options": {"choices": [{"value": c, "label": c} for c in choices]} if choices else {},
        "system": system,
    }


_T, _LONG, _DT = FieldType.TEXT, FieldType.LONGTEXT, FieldType.DATETIME

_FORM: Final = (
    _field("sm_source_page", "Source page", _T, max_length=300),
    _field("sm_source_block", "Source block", _T, max_length=100),
    _field("sm_locale", "Language", _T, max_length=16),
    _field("sm_ip_hash", "IP hash", _T, max_length=64),
    _field("sm_user_agent", "User agent", _T, max_length=256),
    _field("sm_consent_text", "Consent text", _LONG),
    _field("sm_spam", "Spam", FieldType.SELECT, choices=("links", "manual")),
    _field("sm_notified_at", "Notified at", _DT),
    # Which recipients one delivery attempt has reached, so a retry mails only
    # the rest (``public_submissions.mail_runner``). Bookkeeping: internal.
    _field("sm_delivery", "Delivery", _LONG, system=INTERNAL),
)

_SUBSCRIPTION: Final = (
    _field("sm_email", "Email", FieldType.EMAIL, required=True, unique=True, indexed=True),
    _field(
        "sm_status",
        "Status",
        FieldType.SELECT,
        choices=("pending", "confirmed", "unsubscribed"),
        indexed=True,
    ),
    _field("sm_locale", "Language", _T, max_length=16),
    _field("sm_source_page", "Source page", _T, max_length=300),
    _field("sm_consent_text", "Consent text", _LONG),
    _field("sm_consent_at", "Consent given at", _DT),
    _field("sm_confirmed_at", "Confirmed at", _DT),
    _field("sm_unsubscribed_at", "Unsubscribed at", _DT),
    _field("sm_confirm_sent_at", "Confirmation sent at", _DT),
    _field("sm_consent_ip_hash", "Consent IP hash", _T, max_length=64),
    _field("sm_nonce", "Nonce", _T, system=INTERNAL, max_length=32),
)

_BY_KIND: Final = {KIND_FORM: _FORM, KIND_SUBSCRIPTION: _SUBSCRIPTION}


def system_fields(kind: str | None) -> list[dict[str, Any]]:
    """The canonical system field definitions of ``kind`` (none for ``None``),
    as fresh dicts — the caller may mutate them."""
    return copy.deepcopy(list(_BY_KIND.get(kind or "", ())))


def is_system(entry: Any) -> bool:
    """Whether a raw field entry claims to be a system field."""
    return isinstance(entry, dict) and bool(entry.get("system"))


def inject(fields_raw: list[Any], kind: str | None) -> list[Any]:
    """``fields_raw`` with every system entry replaced by ``kind``'s canonical
    ones, appended after the ordinary fields in their declared order."""
    ordinary = [entry for entry in fields_raw if not is_system(entry)]
    return [*ordinary, *system_fields(kind)]
