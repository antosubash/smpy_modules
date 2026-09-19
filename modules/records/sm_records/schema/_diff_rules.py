"""The per-attribute rules :mod:`sm_records.schema.diff` classifies with.

Split from it for the 300-line cap, and the seam is a real one: ``diff.py``
owns *which* fields changed, and this module owns *how* one field's attributes
moved — a constraint tightened or relaxed, a choice gone, a relation
re-pointed. Every function here answers about one pair of definitions of the
same key, and returns the changes that pair produced.
"""

from __future__ import annotations

from typing import Any

from sm_records.schema.changes import SchemaChange
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import ChangeClass

_TIGHTENED_WHEN_RAISED = ("min_length", "min")
"""A floor: raising it invalidates values that used to pass."""
_TIGHTENED_WHEN_LOWERED = ("max_length", "max")
"""A ceiling: lowering it does. ``None`` is the unbounded end of both."""

_LABEL_ATTRS = ("label", "help", "default")
"""Cosmetic, plus ``default`` — which is additive because it is only ever read
where a key is *missing* (:func:`~sm_records.schema.compile.from_stored`), so
changing it cannot invalidate a value any record actually holds."""


def _bound_tightened(before: Any, after: Any, *, raised: bool) -> bool | None:
    """``True`` tightened, ``False`` relaxed, ``None`` unchanged.

    ``None`` on either side is the unbounded end, which is always the looser
    one — dropping a ``max_length`` relaxes, adding one tightens.
    """
    if before == after:
        return None
    if before is None:
        return True
    if after is None:
        return False
    return after > before if raised else after < before


def constraints(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    """One change per constraint that moved, carrying the constraint's name in
    ``before``/``after`` — :class:`SchemaChange` names a field, not a
    constraint, and "which one" is the first thing an operator reading the
    report asks."""
    out: list[SchemaChange] = []
    before_all, after_all = old.constraints or {}, new.constraints or {}
    for name in (*_TIGHTENED_WHEN_RAISED, *_TIGHTENED_WHEN_LOWERED):
        before, after = before_all.get(name), after_all.get(name)
        verdict = _bound_tightened(before, after, raised=name in _TIGHTENED_WHEN_RAISED)
        if verdict is None:
            continue
        out.append(
            SchemaChange(
                kind=ChangeClass.RESTRICTIVE if verdict else ChangeClass.ADDITIVE,
                field_key=new.key,
                what="constraint_tightened" if verdict else "constraint_relaxed",
                before={name: before},
                after={name: after},
            )
        )
    before, after = before_all.get("pattern"), after_all.get("pattern")
    if before != after:
        # A *changed* pattern is tightened, not "changed": the new one can
        # refuse values the old accepted, and nothing short of running it over
        # every row says whether it does. That is the dry run's job.
        relaxed = after is None
        out.append(
            SchemaChange(
                kind=ChangeClass.ADDITIVE if relaxed else ChangeClass.RESTRICTIVE,
                field_key=new.key,
                what="constraint_relaxed" if relaxed else "constraint_tightened",
                before={"pattern": before},
                after={"pattern": after},
            )
        )
    return out


def _choice_map(field: FieldDefinition) -> dict[str, str]:
    choices = (field.options or {}).get("choices") or []
    return {str(c.get("value")): str(c.get("label")) for c in choices if isinstance(c, dict)}


def choices(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    """Values, then labels. Removing a value is restrictive — records holding
    it stop validating; adding one is additive; renaming a label touches no
    stored value at all, since the payload stores the *value*."""
    before, after = _choice_map(old), _choice_map(new)
    out: list[SchemaChange] = []
    gone = [value for value in before if value not in after]
    fresh = [value for value in after if value not in before]
    if gone:
        out.append(SchemaChange(ChangeClass.RESTRICTIVE, new.key, "choice_removed", gone, None))
    if fresh:
        out.append(SchemaChange(ChangeClass.ADDITIVE, new.key, "choice_added", None, fresh))
    relabelled = [v for v in after if v in before and before[v] != after[v]]
    if relabelled:
        out.append(
            SchemaChange(
                kind=ChangeClass.ADDITIVE,
                field_key=new.key,
                what="options_changed",
                before={v: before[v] for v in relabelled},
                after={v: after[v] for v in relabelled},
            )
        )
    return out


def relation(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    """``target_type`` and ``many`` are restrictive: the first invalidates
    every stored reference at once, the second changes the *shape* of the
    stored value (one object ↔ a list of them). ``on_delete`` only decides
    what a future delete does, so it is additive."""
    before, after = old.options or {}, new.options or {}
    out: list[SchemaChange] = []
    for name in ("target_type", "many"):
        if before.get(name) != after.get(name):
            out.append(
                SchemaChange(
                    kind=ChangeClass.RESTRICTIVE,
                    field_key=new.key,
                    what="options_changed",
                    before={name: before.get(name)},
                    after={name: after.get(name)},
                )
            )
    if before.get("on_delete") != after.get("on_delete"):
        out.append(
            SchemaChange(
                kind=ChangeClass.ADDITIVE,
                field_key=new.key,
                what="options_changed",
                before={"on_delete": before.get("on_delete")},
                after={"on_delete": after.get("on_delete")},
            )
        )
    return out


def labels(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    moved = {name for name in _LABEL_ATTRS if getattr(old, name) != getattr(new, name)}
    if not moved:
        return []
    return [
        SchemaChange(
            kind=ChangeClass.ADDITIVE,
            field_key=new.key,
            what="label_changed",
            before={name: getattr(old, name) for name in sorted(moved)},
            after={name: getattr(new, name) for name in sorted(moved)},
        )
    ]
