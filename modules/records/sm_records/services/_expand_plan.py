"""``?expand=`` paths turned into a plan, from the schema alone (#81).

Split from :mod:`sm_records.services.expand` for the 300-line cap, along the
seam between the two passes a nested expansion makes. This one reads only
``records_type``: it walks the requested paths one level at a time, resolves
each hop's *declared* target type, refuses a key that is not a relation field
of the type it is read on, and decides ``restricted`` per hop. The other pass
reads records and never has to ask a schema question.

Two properties are settled here and nowhere else:

* **Validation does not depend on the data.** ``expand=author.nope`` is a 400
  on an empty page exactly as on a full one, because the plan is built before
  a record is read. A refusal that came and went with the page's contents
  would be a refusal a client could not test against.
* **Nothing below a restricted hop is planned.** Not read, and not
  *validated* either: answering ``author.secret_field`` with "unknown" while
  ``author.real_field`` came back as plain ``restricted`` would let a caller
  enumerate the field keys of a type they may not see. Below a target type
  that no longer exists nothing is planned for the same reason nothing is
  read — there is no schema to ask.

One statement per level, for the target types that level introduces; a type
an earlier level already read is not read again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import QueryError
from sm_records.models import RecordType
from sm_records.schema.types import FieldType
from sm_records.services._common import role_blocked

__all__ = ["Hop", "plan", "relation_defs"]

_RELATION = FieldType.RELATION.value


@dataclass
class Hop:
    """One relation field to resolve, on every record its level reaches."""

    path: str
    """The dotted path from the record being read — what a refusal names."""
    target_key: str
    """The field's declared ``target_type``, ``""`` when it has none."""
    target: RecordType | None
    """That type's row; ``None`` when it no longer exists."""
    restricted: bool
    children: dict[str, Hop] = field(default_factory=dict)


def relation_defs(rtype: RecordType) -> dict[str, dict[str, Any]]:
    """The type's ``relation`` fields, by key, as stored JSON.

    The raw definitions rather than ``FieldDefinition`` objects: a read must
    not fail because some *other* field of the type no longer validates, and
    ``field_defs`` validates the lot.
    """
    return {
        str(raw.get("key")): raw
        for raw in (rtype.fields or [])
        if raw.get("type") == _RELATION and raw.get("key")
    }


def _check_keys(rtype: RecordType, keys: Sequence[str], prefix: str) -> dict[str, dict]:
    """Refuse a key that is not a relation field of ``rtype``, by its path.

    ``QueryError`` and not an ad-hoc exception: ``?expand=`` is the same kind
    of promise ``?filter=`` is — "this field key means something on this
    type" — and the endpoint layer already turns that refusal into a 400
    naming the field and the reason. A nested key is named by its whole path
    (``author.nope``), since ``nope`` alone does not say which type lacks it.
    """
    relations = relation_defs(rtype)
    declared = {str(raw.get("key")) for raw in (rtype.fields or []) if raw.get("key")}
    for key in keys:
        if key in relations:
            continue
        path = prefix + key
        if key not in declared:
            raise QueryError(path, "unknown", f"{key!r} is not a field of {rtype.key!r}")
        raise QueryError(
            path, "not_a_relation", f"{key!r} is not a relation field, so it cannot be expanded"
        )
    return relations


def _tree(paths: Sequence[str]) -> dict[str, dict]:
    """``["a.b", "a.c", "d"]`` -> ``{"a": {"b": {}, "c": {}}, "d": {}}``."""
    tree: dict[str, dict] = {}
    for path in paths:
        node = tree
        for key in path.split("."):
            node = node.setdefault(key, {})
    return tree


async def _load_types(db: AsyncSession, keys: set[str], known: dict[str, RecordType]) -> None:
    """Read the target types ``known`` lacks, in one statement."""
    missing = {key for key in keys if key and key not in known}
    if not missing:
        return
    rows = (await db.execute(select(RecordType).where(RecordType.key.in_(missing)))).scalars()
    known.update({row.key: row for row in rows})


async def plan(
    db: AsyncSession,
    rtype: RecordType,
    paths: Sequence[str],
    roles: Sequence[str] | None,
) -> dict[str, Hop]:
    """The hops of ``paths`` on ``rtype``, nested as the paths are."""
    root: dict[str, Hop] = {}
    known: dict[str, RecordType] = {}
    # (type read on, its requested subtree, path prefix, where its hops go)
    level: list[tuple[RecordType, dict[str, dict], str, dict[str, Hop]]] = [
        (rtype, _tree(paths), "", root)
    ]
    while level:
        checked = [(item, _check_keys(item[0], list(item[1]), item[2])) for item in level]
        targets = {
            str((relations[key].get("options") or {}).get("target_type") or "")
            for (_, subtree, _, _), relations in checked
            for key in subtree
        }
        await _load_types(db, targets, known)
        next_level = []
        for (_, subtree, prefix, out), relations in checked:
            for key, children in subtree.items():
                target_key = str((relations[key].get("options") or {}).get("target_type") or "")
                target = known.get(target_key)
                hop = Hop(
                    path=prefix + key,
                    target_key=target_key,
                    target=target,
                    restricted=target is not None and role_blocked(target, roles),
                )
                out[key] = hop
                if children and target is not None and not hop.restricted:
                    next_level.append((target, children, f"{hop.path}.", hop.children))
        level = next_level
    return root
