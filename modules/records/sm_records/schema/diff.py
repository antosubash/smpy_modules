"""Classifying one field list against another — design doc §8.2.

Pure: no database, no session, no settings. Everything §8 decides about a
proposed schema edit starts here, and the decision has to be reproducible from
the two lists alone — the dry run (which records would fail), the index
migration (which keys move between tables) and the refusal (is this additive
or does it need a ``force``) all read this output rather than re-deriving it.

**Fields are matched by ``key``, and only by ``key``.** There is no rename in
the taxonomy (§8.7): a rename would decompose into destructive-then-additive
and silently blank a column of content, so ``key`` is immutable and a changed
key is a removal plus an addition. Reordering alone is therefore not a change
at all — the list's order is presentation.

One change may be classified twice. A type change on an indexed field is
``RESTRICTIVE`` (coercion can fail) *and* ``INDEX_AFFECTING`` (its rows move
between tables, §8.5), and both readers need to see it: the dry run would
otherwise skip it, or the reindex would never be enqueued.
"""

from __future__ import annotations

from sm_records.schema._diff_rules import choices, constraints, labels, relation
from sm_records.schema.changes import SchemaChange, SchemaDiff
from sm_records.schema.fields import FieldDefinition
from sm_records.schema.types import ChangeClass, FieldType

__all__ = ["diff_fields"]


def _added(new: FieldDefinition) -> list[SchemaChange]:
    """A key that was not there before.

    Additive unless the field is required with nothing to fill it: every
    existing record is missing the key, so it reads as the default, and a
    required field with no default makes every one of them invalid at once.
    """
    restrictive = new.required and new.default is None
    out = [
        SchemaChange(
            kind=ChangeClass.RESTRICTIVE if restrictive else ChangeClass.ADDITIVE,
            field_key=new.key,
            what="field_added",
            before=None,
            after=new.type.value,
        )
    ]
    if new.indexed:
        out.append(
            SchemaChange(
                kind=ChangeClass.INDEX_AFFECTING,
                field_key=new.key,
                what="indexed_on",
                before=None,
                after=True,
            )
        )
    return out


def _removed(old: FieldDefinition) -> list[SchemaChange]:
    """A key that is gone.

    Destructive — the values stay in the payload under ``_orphaned`` (§8.3),
    but the field stops existing — *and* index-affecting, because the key's
    index rows have to go: they are derived from a definition that no longer
    exists, and a query that still read them would be answering from a field
    nobody can see. Emitted even for an unindexed field, where the delete
    matches nothing: the alternative is a rule about which removals need
    cleaning up, and a wrong one leaves rows behind for good.
    """
    return [
        SchemaChange(
            kind=ChangeClass.DESTRUCTIVE,
            field_key=old.key,
            what="field_removed",
            before=old.type.value,
            after=None,
        ),
        SchemaChange(
            kind=ChangeClass.INDEX_AFFECTING,
            field_key=old.key,
            what="indexed_off",
            before=old.indexed,
            after=None,
        ),
    ]


def _type_change(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    """Always restrictive: *any* type change can fail to coerce for some row,
    and which rows is exactly what the dry run is for (§8.4). Index-affecting
    as well when either side is indexed, because the rows move from one index
    table to another and both sets exist mid-rebuild (§8.5)."""
    out = [
        SchemaChange(
            kind=ChangeClass.RESTRICTIVE,
            field_key=new.key,
            what="type_changed",
            before=old.type.value,
            after=new.type.value,
        )
    ]
    if old.indexed or new.indexed:
        out.append(
            SchemaChange(
                kind=ChangeClass.INDEX_AFFECTING,
                field_key=new.key,
                what="type_changed",
                before=old.type.value,
                after=new.type.value,
            )
        )
    return out


def _flags(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    out: list[SchemaChange] = []
    if old.required != new.required:
        # Turning ``required`` on is only restrictive without a default: with
        # one, every record missing the key reads as that value and passes.
        restrictive = new.required and new.default is None
        out.append(
            SchemaChange(
                kind=ChangeClass.RESTRICTIVE if restrictive else ChangeClass.ADDITIVE,
                field_key=new.key,
                what="required_added" if new.required else "required_removed",
                before=old.required,
                after=new.required,
            )
        )
    if old.unique != new.unique:
        # Newly unique is restrictive because the records that exist may
        # already hold duplicates — nothing checked them until now (§7.8).
        # Restrictive is only a promise if something can *see* the failure,
        # and the per-record dry run cannot: duplication is a property of a
        # pair. ``services._duplicates`` is the scan that keeps this
        # classification honest, and it keys on this ``what`` value.
        out.append(
            SchemaChange(
                kind=ChangeClass.RESTRICTIVE if new.unique else ChangeClass.ADDITIVE,
                field_key=new.key,
                what="unique_added" if new.unique else "unique_removed",
                before=old.unique,
                after=new.unique,
            )
        )
    if old.indexed != new.indexed:
        out.append(
            SchemaChange(
                kind=ChangeClass.INDEX_AFFECTING,
                field_key=new.key,
                what="indexed_on" if new.indexed else "indexed_off",
                before=old.indexed,
                after=new.indexed,
            )
        )
    return out


def _compare(old: FieldDefinition, new: FieldDefinition) -> list[SchemaChange]:
    if old.type is not new.type:
        # Constraints and options are per-type, so comparing them across a type
        # change compares two vocabularies. The type change subsumes them.
        return [*_type_change(old, new), *_flags(old, new), *labels(old, new)]
    out = [*_flags(old, new), *constraints(old, new)]
    if new.type in (FieldType.SELECT, FieldType.MULTISELECT):
        out += choices(old, new)
    elif new.type is FieldType.RELATION:
        out += relation(old, new)
    return [*out, *labels(old, new)]


def diff_fields(old: list[FieldDefinition], new: list[FieldDefinition]) -> SchemaDiff:
    """Classify every difference between two *validated* field lists.

    Both sides must already be through
    :func:`~sm_records.schema.fields.validate_fields` — the normalised form is
    what the type stores, and diffing raw input against a normalised list
    reports changes nobody made (``unique`` implying ``indexed``, a defaulted
    ``on_delete``).
    """
    by_key_old = {field.key: field for field in old}
    by_key_new = {field.key: field for field in new}
    changes: list[SchemaChange] = []
    for field in new:
        previous = by_key_old.get(field.key)
        changes += _added(field) if previous is None else _compare(previous, field)
    for field in old:
        if field.key not in by_key_new:
            changes += _removed(field)
    return SchemaDiff(changes=tuple(changes))
