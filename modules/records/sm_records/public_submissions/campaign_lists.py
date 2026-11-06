"""List creation and field reads/extension for newsletter's Mailchimp import.

The contract, :mod:`sm_records.contracts.newsletter_import`, binds the tenant;
the type writes live here. Nothing here commits.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordType
from sm_records.public_submissions.campaign_reads import KIND_SUBSCRIPTION
from sm_records.records.services import types as type_service
from sm_records.records.services._common import record_count
from sm_records.records.services._lock import lock_type
from sm_records.records.services.errors import Conflict, ValidationFailed
from sm_records.schema.types import FieldType

__all__ = [
    "MAPPABLE_TYPES",
    "MAX_CHOICE_LEN",
    "MAX_NEW_CHOICES",
    "TAGS_FIELD",
    "InvalidListKey",
    "ListExists",
    "TagsFieldMissing",
    "add_choices",
    "create",
    "mappable_fields",
    "tags_field",
    "tags_state",
]

MAPPABLE_TYPES = ("text", "longtext", "email", "url", "select")
TAGS_FIELD = "tags"
MAX_NEW_CHOICES = 500
MAX_CHOICE_LEN = 100
_MULTISELECT = FieldType.MULTISELECT.value


class ListExists(Exception):  # noqa: N818 - contract vocabulary
    """``create_list``: the key is taken in this tenant."""


class InvalidListKey(ValueError):  # noqa: N818 - contract vocabulary
    """``create_list``: records refused the key or the label."""


class TagsFieldMissing(LookupError):  # noqa: N818 - contract vocabulary
    """``add_tag_choices``: the list has no ``tags`` multiselect and cannot get one."""


def _name_field(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": "text",
        "label": key.replace("_", " ").title(),
        "required": False,
        "unique": False,
        "indexed": False,
        "default": None,
        "help": None,
        "constraints": {"max_length": 100},
        "options": {},
    }


async def create(
    db: AsyncSession, *, key: str, label: str, settings: RecordsSettings, actor: str | None
) -> str:
    try:
        rtype = await type_service.create_type(
            db,
            key=key,
            label=label,
            settings=settings,
            fields_raw=[_name_field("first_name"), _name_field("last_name")],
            public_submissions={"kind": KIND_SUBSCRIPTION},
            show_in_menu=True,
            actor=actor,
        )
    except Conflict as exc:
        raise ListExists(key) from exc
    except ValidationFailed as exc:
        raise InvalidListKey(str(exc)) from exc
    return rtype.key


def mappable_fields(rtype: RecordType) -> list[dict[str, Any]]:
    """Ordinary (not system) fields an import can fill, not ``tags``, in order."""
    fields = [f for f in rtype.fields or [] if isinstance(f, dict) and not f.get("system")]
    return [f for f in fields if f.get("key") != TAGS_FIELD and f.get("type") in MAPPABLE_TYPES]


def tags_field(rtype: RecordType) -> dict[str, Any] | None:
    """The list's ``tags`` field definition, indexed or not; ``None`` without one."""
    fields = [f for f in rtype.fields or [] if isinstance(f, dict)]
    return next((f for f in fields if f.get("key") == TAGS_FIELD), None)


async def tags_state(
    db: AsyncSession, rtype: RecordType
) -> Literal["present", "creatable", "missing"]:
    tags = tags_field(rtype)
    if tags is not None:
        return "present" if tags.get("type") == _MULTISELECT else "missing"
    held = await record_count(db, rtype, include_deleted=True)
    return "missing" if held else "creatable"


def _checked(choices: object) -> list[tuple[str, str]]:
    if isinstance(choices, str) or not isinstance(choices, Sequence):
        raise ValueError("choices must be a sequence")
    if len(choices) > MAX_NEW_CHOICES:
        raise ValueError(f"at most {MAX_NEW_CHOICES} choices")
    out: list[tuple[str, str]] = []
    for choice in choices:
        pair = (getattr(choice, "value", None), getattr(choice, "label", None))
        for text in pair:
            if (
                not isinstance(text, str)
                or not 1 <= len(text) <= MAX_CHOICE_LEN
                or any(unicodedata.category(c) == "Cc" for c in text)
            ):
                raise ValueError(
                    f"a choice value and label are 1-{MAX_CHOICE_LEN} characters, "
                    "without control characters"
                )
        out.append(pair)  # type: ignore[arg-type]
    if len({v for v, _ in out}) != len(out):
        raise ValueError("duplicate choice values")
    return out


def _with_choices(
    rtype: RecordType, wanted: list[tuple[str, str]], held: int
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """The fields with the missing choices appended, and those values; ``None``
    when ``tags`` is absent and cannot be created."""
    fields = [dict(f) if isinstance(f, dict) else f for f in rtype.fields or []]
    tags = next((f for f in fields if isinstance(f, dict) and f.get("key") == TAGS_FIELD), None)
    if tags is None:
        if held:
            return None
        tags = {
            "key": TAGS_FIELD,
            "type": _MULTISELECT,
            "label": "Tags",
            "indexed": True,
            "options": {"choices": []},
        }
        fields.append(tags)
    elif tags.get("type") != _MULTISELECT:
        return None
    options = dict(tags.get("options") or {})
    choices = [dict(c) for c in options.get("choices") or [] if isinstance(c, dict)]
    known = {c.get("value") for c in choices}
    added = [(v, lab) for v, lab in wanted if v not in known]
    choices.extend({"value": v, "label": lab} for v, lab in added)
    tags["options"] = {**options, "choices": choices}
    return fields, [v for v, _ in added]


async def add_choices(
    db: AsyncSession,
    rtype: RecordType,
    choices: Sequence[Any],
    *,
    settings: RecordsSettings,
    actor: str | None,
) -> list[str]:
    wanted = _checked(choices)
    await lock_type(db, rtype)
    for attempt in (1, 2):  # one retry on a lost version race
        await db.refresh(rtype)
        held = await record_count(db, rtype, include_deleted=True)
        built = _with_choices(rtype, wanted, held)
        if built is None:
            raise TagsFieldMissing(rtype.key)
        fields, added = built
        if not added:
            return []
        try:
            await type_service.update_type(
                db,
                rtype,
                fields_raw=fields,
                expected_version=rtype.version,
                settings=settings,
                actor=actor,
            )
        except Conflict:
            if attempt == 2:
                raise
            continue
        return added
    return []  # pragma: no cover
