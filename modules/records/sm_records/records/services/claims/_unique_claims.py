"""records services _unique_claims helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core._text import NUL_PROBLEM, has_nul
from sm_records.models import RecordType, tables_for
from sm_records.records.index.query import Filter, FilterOp, QueryError, exists_query
from sm_records.records.services.errors import Conflict, ValidationFailed
from sm_records.schema.fields import FieldDefinition


async def ensure_unique(
    db: AsyncSession,
    rtype: RecordType,
    defs: list[FieldDefinition],
    values: dict[str, Any],
    *,
    exclude_id: int | None = None,
    exclude_group: str | None = None,
    previous: dict[str, Any] | None = None,
) -> None:
    """Design §7.8: ``unique`` is application-enforced, against the index.

    The ``(type_id, field_key, value)`` index cannot carry a unique constraint
    — every field of a kind shares the table and the keys are chosen at
    runtime — so this is a ``SELECT`` before the write, inside the request's
    transaction, serialised per type by :func:`lock_type`.

    ``exists_query`` rather than a hand-written select, so the truncation
    re-check of §7.4 (``value`` *and* ``value_full``) is the same code a
    filter uses. It is an existence check (``SELECT ... LIMIT 1``) and not the
    list page's ``COUNT``: the question is "is this value taken", which one
    row settles, and asking how many rows hold it made every write to a type
    with a ``unique`` field cost a full pass over that type — 50% of a create
    at 15,000 rows, and the reason the demo seeder fell to 14 rec/s.
    ``include_deleted`` for the same reason as the slug: index rows survive a
    soft delete (§7.3) and the trash keeps its claims, so a trashed record
    still owns its unique value until it is purged.

    **The statement is built inside the ``try``**, because that is where the
    failure is: ``exists_query`` refuses a field with a ``reindex_pending``
    marker (§8.5) while it is being *built*, not when it runs. Built outside,
    the ``QueryError`` escaped as the query grammar's own 400/409 about a
    filter the caller never wrote — and this branch, which says the true
    thing (the write cannot be checked, so it is refused), was unreachable.
    A ``QueryError`` for any other reason is re-raised untouched: a ``unique``
    field that is somehow not indexed is a broken definition, not a rebuild.

    **``exclude_group`` is what makes a ``unique`` field survive translation.**
    ``unique`` is type-level and locale-blind, so without it the sibling that
    :func:`~sm_records.records.services.translations._translations.create_translation` copies the
    payload into collides with its own source — a German product cannot carry
    the English product's SKU, which is exactly what a SKU is for. The rule is
    therefore *uniqueness among records that are not siblings*: rows sharing a
    ``translation_group`` are exempt from each other's claims, and everything
    else collides as before — two records in the same language, or two records
    in different languages that belong to different groups. It is the same
    mechanism as ``exclude_id``, one level up: that one exempts the row being
    rewritten, this one the group it belongs to. The group is known before the
    write in all three callers (a create's is its own new uuid, an update's is
    the row's, a translation's is the source's), so this costs no query.

    A trashed sibling is still a sibling and still exempt; a trashed
    *non*-sibling still blocks, because ``include_deleted`` keeps the trash's
    claims and a restore must find them intact.

    **``previous`` exempts a value this record already holds.** A write does
    not *make* a claim it is already making, and refusing one is how a record
    becomes unsaveable rather than merely wrong: a ``unique`` flag forced onto
    a field that already held duplicates (§8.2) leaves two records sharing a
    value, and without this every subsequent write to either — a status
    change, a typo fixed in an unrelated field — was a 409 about a field the
    write did not touch, with no path back except turning ``unique`` off
    again. The check still refuses a *third* record reaching for that value,
    and still refuses either of the two moving to some other taken one, so the
    rule §7.8 states is unchanged for every claim that is actually new. It is
    the coerced view that is compared, not the raw payload, because that is
    what the index row is projected from and therefore what "the same claim"
    means.
    """
    for field in defs:
        if not field.unique:
            continue
        value = values.get(field.key)
        if value is None or (previous is not None and previous.get(field.key) == value):
            continue
        # A unique claim is an index lookup, i.e. a bound ``text`` parameter.
        # The payload validator refuses a NUL long before this, so reaching
        # here means the value came from somewhere else — a custom provider's
        # projection, or a row written before that rule. Answering the claim
        # with the driver's ``CharacterNotInRepertoireError`` would be a 500 on
        # a write whose real problem is one unstorable character.
        if has_nul(value):
            raise ValidationFailed(
                f"{field.key!r} {NUL_PROBLEM}", [{"field": field.key, "message": NUL_PROBLEM}]
            )
        if await taken_by(
            db, rtype, field, value, exclude_id=exclude_id, exclude_group=exclude_group
        ):
            raise Conflict(f"{field.key!r} must be unique; {value!r} is already taken")


async def taken_by(
    db: AsyncSession,
    rtype: RecordType,
    field: FieldDefinition,
    value: Any,
    *,
    exclude_id: int | None = None,
    exclude_group: str | None = None,
) -> bool:
    """Does any *other* record of ``rtype`` already hold ``value`` in ``field``?

    The statement :func:`ensure_unique` used to build inline, lifted so the
    read-only caller that asks the same question can ask it the same way —
    :func:`sm_records.records.services.schema_changes._duplicates.conflicts_for`, which turns the
    answer into the ``invalid`` badge a record left duplicated by a forced
    ``unique_added`` wears. A second spelling of this query would be a second
    opinion about what "already taken" means.
    """
    # ``False`` and not a refusal: this is the read-only question the record
    # editor asks for its duplicate badge (``services._duplicates``), and a
    # value the index cannot hold is a value no other record can be holding.
    # The write path refuses it a few lines up, where a refusal is useful.
    if has_nul(value):
        return False
    record = tables_for(rtype).record
    try:
        stmt = exists_query(
            rtype, list(rtype.fields or []), [Filter(field.key, FilterOp.EQ, value)]
        )
        if exclude_id is not None:
            stmt = stmt.where(record.id != exclude_id)
        if exclude_group is not None:
            stmt = stmt.where(record.translation_group != exclude_group)
        taken = (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()
    except QueryError as exc:
        if exc.reason != "reindexing":
            raise
        raise Conflict(
            f"{field.key!r} is being reindexed, so its uniqueness cannot be checked; "
            "writes to this type are refused until the rebuild completes"
        ) from exc
    return taken is not None
