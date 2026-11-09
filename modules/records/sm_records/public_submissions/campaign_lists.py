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
from sm_records.public_submissions.tag_values import tag_values
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


def _checked(labels: object) -> list[str]:
    if isinstance(labels, str) or not isinstance(labels, Sequence):
        raise ValueError("labels must be a sequence of str")
    if len(labels) > MAX_NEW_CHOICES:
        raise ValueError(f"at most {MAX_NEW_CHOICES} labels")
    for text in labels:
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= MAX_CHOICE_LEN
            or any(unicodedata.category(c) == "Cc" for c in text)
        ):
            raise ValueError(
                f"a label is 1-{MAX_CHOICE_LEN} characters, without control characters"
            )
    if len(set(labels)) != len(labels):
        raise ValueError("duplicate labels")
    return list(labels)


def _tags_in(fields: list[Any], held: int) -> dict[str, Any] | None:
    """The ``tags`` multiselect in ``fields`` (appended, empty, on a list with no
    records); ``None`` when it is absent and cannot be created, or not one."""
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
    return tags if tags.get("type") == _MULTISELECT else None


def _pairs(choices: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out = []
    for c in choices:
        value = str(c.get("value"))
        out.append((value, str(c.get("label") or value)))
    return out


async def add_choices(
    db: AsyncSession,
    rtype: RecordType,
    labels: Sequence[Any],
    *,
    settings: RecordsSettings,
    actor: str | None,
) -> dict[str, str]:
    """Each label's choice value, decided (:func:`.tag_values.tag_values`) and the
    missing ones appended under the type lock, from the choices as they are then."""
    wanted = _checked(labels)
    if not wanted:
        return {}
    await lock_type(db, rtype)
    for attempt in (1, 2):  # one retry on a lost version race
        await db.refresh(rtype)
        fields = [dict(f) if isinstance(f, dict) else f for f in rtype.fields or []]
        # The count only decides whether a missing field can be created.
        has_tags = any(isinstance(f, dict) and f.get("key") == TAGS_FIELD for f in fields)
        held = 0 if has_tags else await record_count(db, rtype, include_deleted=True)
        tags = _tags_in(fields, held)
        if tags is None:
            raise TagsFieldMissing(rtype.key)
        options = dict(tags.get("options") or {})
        choices = [dict(c) for c in options.get("choices") or [] if isinstance(c, dict)]
        current = _pairs(choices)
        mapping = tag_values(wanted, current)
        known = {value for value, _ in current}
        added = [label for label in wanted if mapping[label] not in known]
        if not added:
            return mapping
        choices.extend({"value": mapping[label], "label": label} for label in added)
        tags["options"] = {**options, "choices": choices}
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
        return mapping
    return {}  # pragma: no cover
