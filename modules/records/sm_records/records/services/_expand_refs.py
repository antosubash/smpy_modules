"""records services _expand_refs helpers."""

from __future__ import annotations
from sm_records.core.constants import MAX_DISPLAY_TITLE_LEN
from sm_records.models import Record, RecordType
from sm_records.records.services._expand_plan import relation_defs


def relation_field_keys(rtype: RecordType) -> list[str]:
    """Every relation field of the type, in declaration order.

    What the admin screens expand: §9's "the generic list screen is the one
    caller that always passes it" — a column of bare UUIDs is not a list
    screen, and the editor has to show a title next to a relation picker.
    """
    return list(relation_defs(rtype))


def _refs(record: Record, field_key: str, declared: str) -> list[tuple[str, str, bool]]:
    """``(type key, uuid, resolvable)`` per stored entry, **in payload order**.

    A to-many field's expansion has to line up with ``data[key]``
    positionally — the UI renders the two together — so the list is built
    from the payload and never from the index rows, which carry no order.

    **A field that holds nothing expands to nothing.** ``validate_payload``
    dumps every declared key, so a relation nobody filled in is stored as
    ``None`` — on every record of the type, to-one and to-many alike — and an
    empty to-many is stored as ``[]``. Neither is a reference the caller left
    broken, so neither produces an entry: the alternative was one phantom
    ``dangling`` chip reading ``uuid: "None"`` on every unset relation, and a
    "dangling references" count that was really a count of empty fields.

    **Every entry of a list produces one tuple, including one that is not a
    reference at all.** That is the positional rule, and it is about entries
    *inside* a list: a ``null`` in the middle of a to-many used to be skipped,
    which shortened the expansion and put every later slot out of step with
    the payload it is rendered beside — ``expanded[1]`` labelling ``data[2]``.
    Such an entry is marked unresolvable here and comes back ``dangling``,
    carrying the stored value stringified as its ``uuid`` so the position is
    visible rather than silently plausible. Writes cannot create one any more
    (``schema._builders._check_ref_list``); rows written before that check
    can. A single (non-list) value that is not a reference object keeps the
    same treatment for the same reason — it is a corrupt value and saying so
    is the point — but ``None`` is not corrupt, it is empty.

    The stored ``type`` is echoed when the payload has one and the field's
    declared target substituted when it does not. The two are allowed to
    disagree on a row written before ``_relations.check_targets`` existed,
    and :func:`_targets` is what refuses to resolve such a row.
    """
    value = (record.data or {}).get(field_key)
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[tuple[str, str, bool]] = []
    for item in items:
        if isinstance(item, dict) and item.get("uuid"):
            out.append((str(item.get("type") or declared), str(item["uuid"]), True))
        else:
            out.append((declared, str(item)[:MAX_DISPLAY_TITLE_LEN], False))
    return out


def _live(target: Record | None) -> Record | None:
    """A trashed row is not a resolvable target — §9's ``dangling``, reached
    without the second lookup that telling it from a purge would cost."""
    return None if target is None or target.is_deleted else target
