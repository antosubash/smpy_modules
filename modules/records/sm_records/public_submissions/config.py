"""The rules a type's ``public_submissions`` config must obey on save (#101).

:func:`parse` checks the shape (:class:`PublicSubmissionsConfig`);
:func:`check_change` the two rules about *changing* it, which need the stored
row and a count; :func:`settle` everything that depends on the type's fields
and ``is_public`` — run by create and by every type-row write
(``services._schema.write_type_row``), so an update, a schema change, a
rollback and an import all meet it.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records._text import has_nul
from sm_records.constants import LOCALE_PATTERN
from sm_records.contracts.public_submissions import (
    KIND_SUBSCRIPTION,
    MAX_CONSENT_TEXT_LEN,
    PublicSubmissionsConfig,
)
from sm_records.models import RecordType
from sm_records.public_submissions.spec import SUBMITTABLE_TYPES, is_system
from sm_records.services._common import record_count
from sm_records.services._lock import lock_type
from sm_records.services.errors import Conflict, ValidationFailed

__all__ = ["FIELD", "check_change", "default_display", "kind_of", "parse", "settle"]

FIELD = "public_submissions"
_LOCALE_RE = re.compile(LOCALE_PATTERN)
_SUBMITTABLE = frozenset(member.value for member in SUBMITTABLE_TYPES)


def _refuse(problem: str, where: str = FIELD) -> ValidationFailed:
    return ValidationFailed(problem, [{"field": where, "message": problem}])


def parse(raw: Any) -> dict[str, Any] | None:
    """The config in its stored form — defaults filled — or ``None``."""
    if raw is None:
        return None
    try:
        config = PublicSubmissionsConfig.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in (FIELD, *first["loc"]))
        raise ValidationFailed(
            f"{where}: {first['msg']}", [{"field": FIELD, "message": f"{where}: {first['msg']}"}]
        ) from exc
    return config.model_dump(mode="json")


def kind_of(rtype: RecordType | None, changes: dict[str, Any] | None = None) -> str | None:
    """The kind a write leaves the type with — the sent config's, else the
    stored one's. They cannot disagree once :func:`check_change` has run."""
    changes = changes or {}
    config = changes[FIELD] if FIELD in changes else getattr(rtype, FIELD, None)
    return (config or {}).get("kind")


def default_display(config: dict[str, Any] | None, display_field: str | None) -> str | None:
    """A newsletter type lists its subscribers by address unless told otherwise."""
    if display_field is None and config and config["kind"] == KIND_SUBSCRIPTION:
        return "sm_email"
    return display_field


async def check_change(db: AsyncSession, rtype: RecordType, changes: dict[str, Any]) -> bool:
    """Normalise ``changes["public_submissions"]`` in place and refuse what may
    not change. Returns whether this write gives the type its kind.

    **The kind is set once.** Clearing it, or turning a form into a newsletter,
    would leave system fields that nothing writes any more (409); deleting the
    type is the way out. **A newsletter kind needs an empty type** (409): its
    ``sm_email`` is required and unique, which no record written before has —
    a schema change the dry run would refuse anyway, said here with the reason.
    """
    if FIELD not in changes:
        return False
    config = changes[FIELD] = parse(changes[FIELD])
    before = (rtype.public_submissions or {}).get("kind")
    after = (config or {}).get("kind")
    if before is not None and after != before:
        raise Conflict(
            f"type {rtype.key!r} accepts {before} submissions; that cannot be turned "
            "off or changed once set — delete the type instead"
        )
    if before is None and after == KIND_SUBSCRIPTION:
        # Under the type's lock, which every record write takes first: a
        # record created between this count and the commit would be a
        # subscriber with no address.
        await lock_type(db, rtype)
        if await record_count(db, rtype, include_deleted=True):
            raise Conflict(
                "only a type with no records can become a newsletter list: every "
                "subscriber needs an address, and the records already stored have none"
            )
    return before is None and after is not None


def _check_consent(config: dict[str, Any]) -> None:
    consent = config["consent"]
    for locale, text in consent["text"].items():
        if not _LOCALE_RE.match(locale):
            raise _refuse(f"consent text locale {locale!r} is not a valid locale")
        if len(text) > MAX_CONSENT_TEXT_LEN:
            raise _refuse(
                f"consent text ({locale}) must be at most {MAX_CONSENT_TEXT_LEN} characters"
            )
        if has_nul(text):
            raise _refuse(f"consent text ({locale}) must not contain NUL characters")
    no_opt_in = config["kind"] == KIND_SUBSCRIPTION and not config["double_opt_in"]
    if no_opt_in and not consent["required"]:
        raise _refuse("a newsletter without double opt-in has to require consent")
    if consent["required"] and not any(text.strip() for text in consent["text"].values()):
        raise _refuse("required consent needs the text the visitor agrees to")


def settle(
    config: dict[str, Any] | None, fields: list[dict[str, Any]], is_public: bool
) -> dict[str, Any] | None:
    """Check ``config`` against the type it is about to be stored on, and
    return it with ``public_fields`` pruned of fields that no longer exist —
    removing a field takes it off a live form in the same write.

    ``fields`` is the normalised stored form (``services._schema.normalise``).
    """
    if config is None:
        return None
    if is_public:
        # The anonymous read API would publish what visitors sent, which is
        # personal data. Submissions are also always stored as drafts.
        raise Conflict(
            "a type that accepts submissions from the website cannot also be public: "
            "the public read API would publish what visitors sent"
        )
    ordinary = {entry["key"]: entry for entry in fields if not is_system(entry)}
    system_keys = {entry["key"] for entry in fields if is_system(entry)}
    public = [key for key in config["public_fields"] if key in ordinary or key in system_keys]
    for key in public:
        entry = ordinary.get(key)
        if entry is None:
            raise _refuse(f"{key!r} is a system field; visitors cannot fill it in")
        if entry["type"] not in _SUBMITTABLE:
            raise _refuse(f"{key!r} is a {entry['type']} field, which visitors cannot fill in")
        if entry.get("unique"):
            # A duplicate would be refused with a 409, telling an anonymous
            # visitor what another visitor already sent.
            raise _refuse(f"{key!r} is unique, so visitors cannot fill it in")
    if config["enabled"]:
        missing = [
            key
            for key, entry in ordinary.items()
            if entry.get("required") and entry.get("default") is None and key not in public
        ]
        if missing:
            raise _refuse(
                f"required field(s) {missing} have no default and are not public, so every "
                "submission would be refused; make them public, optional or give them a default"
            )
    _check_consent(config)
    return {**config, "public_fields": public}
