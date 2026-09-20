"""The two claims a record write makes that no database constraint can hold,
and the lock that makes them hold anyway.

The ``unique`` rule of design §7.8 and the slug rule of §5 are both
*check-then-act*: a ``SELECT`` inside the write's transaction, then an
``INSERT`` that assumes the answer is still true. Neither can be a constraint
the database enforces on its own — the index tables are shared across every
field of a kind, so a unique index naming a runtime-chosen field key is not
expressible — so what closes the window is :func:`lock_type`, and what catches
the one case the database *can* express is :func:`flush_write`.

Split out of :mod:`sm_records.services._payload` for the file cap, along the
seam that was already there: that module is "what the write does to the
payload", and this one is "what the write claims about the rest of the type".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import Filter, FilterOp, QueryError, exists_query
from sm_records.models import (
    GROUP_LOCALE_CONFLICT_SIGNATURES,
    SLUG_CONFLICT_SIGNATURES,
    Record,
    RecordType,
)
from sm_records.schema.fields import FieldDefinition
from sm_records.services.errors import Conflict

__all__ = ["ensure_slug_free", "ensure_unique", "flush_write", "lock_type"]


def _slug_taken(type_key: str, slug: str, locale: str) -> Conflict:
    """One wording for the two places a slug collision is discovered.

    It takes the key as a string rather than the ``RecordType`` because one of
    those places is *after a failed flush*, where every instance in the session
    is expired and reading ``rtype.key`` would emit a refresh ``SELECT`` on a
    transaction that can only be rolled back — turning the 409 into a
    ``PendingRollbackError``. ``locale`` travels for the same reason and says
    *which* namespace is occupied: the same word is a legal address in every
    other language (Phase 5 §4.3), so a message that did not name one would
    read as a refusal the caller cannot work around.
    """
    return Conflict(f"slug {slug!r} is already used by another {type_key} record in {locale!r}")


def _group_locale_taken(type_key: str, locale: str) -> Conflict:
    """The database's own refusal of a second record in one language of one
    translation group — :data:`~sm_records.models.GROUP_LOCALE_CONFLICT_SIGNATURES`.

    Reached by a writer that sets ``translation_group`` itself: an import
    carrying the column, or a second ``POST /translations`` that lost the race
    with the first. The endpoint's own check answers the ordinary case; this is
    what keeps the race a 409 rather than a 500.
    """
    return Conflict(f"a {type_key} record in {locale!r} already exists in that translation group")


async def ensure_slug_free(
    db: AsyncSession,
    rtype: RecordType,
    slug: str | None,
    locale: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """A slug is unique within its type **and its locale**, including the trash
    (design §5, Phase 5 §4.3).

    ``locale`` is a positional argument and not a keyword with a default, on
    purpose: every slug lookup and every slug claim in this module takes one,
    and a default would let exactly the call that forgot it fall back to the
    English namespace — which is how ``?locale=de`` starts serving the English
    record. The predicate has to match the partial unique index's key column
    for column, or the check and the constraint disagree about what a
    collision is.

    ``include_deleted`` is the rest of the point: a slug that frees on delete
    is a slug that can be taken while the original sits restorable, and the
    restore then fails or silently renames. The partial unique index would
    catch this at the DB anyway — checking here turns an ``IntegrityError`` at
    flush into a 409 that names the field.
    """
    if slug is None:
        return
    stmt = select(Record.id).where(
        Record.type_id == rtype.id, Record.locale == locale, Record.slug == slug
    )
    if exclude_id is not None:
        stmt = stmt.where(Record.id != exclude_id)
    taken = (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()
    if taken is not None:
        raise _slug_taken(rtype.key, slug, locale)


async def flush_write(db: AsyncSession, rtype: RecordType, slug: str | None, locale: str) -> None:
    """Flush a record write, turning the slug index's own refusal into the 409
    :func:`ensure_slug_free` would have raised.

    :func:`ensure_slug_free` is the check, and between it and this flush there
    is a window another writer can take the slug in — :func:`lock_type` closes
    it, but only for callers that go through this module's write path, and the
    partial unique index is what closes it for everybody else. Its refusal
    arrived as an unhandled ``IntegrityError``, i.e. a 500 on the exact race
    the constraint exists to lose gracefully. Mapping it here means the
    database-level failure and the application-level check produce the same
    error, and neither is the authority on the wording.

    Recognised by :data:`~sm_records.models.SLUG_CONFLICT_SIGNATURES` and
    :data:`~sm_records.models.GROUP_LOCALE_CONFLICT_SIGNATURES`, which is where
    the per-dialect wording lives; anything else is re-raised, because an
    ``IntegrityError`` this module cannot explain is a bug rather than a 409.

    ``rtype.key`` is read **before** the flush. A flush that raises expires
    every instance in the session, so reading it afterwards would emit a
    refresh on a transaction that now accepts nothing but a rollback.
    """
    type_key = rtype.key
    try:
        await db.flush()
    except IntegrityError as exc:
        message = str(exc.orig or exc)
        if any(sig in message for sig in GROUP_LOCALE_CONFLICT_SIGNATURES):
            raise _group_locale_taken(type_key, locale) from exc
        if slug is None or not any(sig in message for sig in SLUG_CONFLICT_SIGNATURES):
            raise
        raise _slug_taken(type_key, slug, locale) from exc


async def ensure_unique(
    db: AsyncSession,
    rtype: RecordType,
    defs: list[FieldDefinition],
    values: dict[str, Any],
    *,
    exclude_id: int | None = None,
    exclude_group: str | None = None,
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
    :func:`~sm_records.services._translations.create_translation` copies the
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
    """
    for field in defs:
        if not field.unique:
            continue
        value = values.get(field.key)
        if value is None:
            continue
        try:
            stmt = exists_query(
                rtype, list(rtype.fields or []), [Filter(field.key, FilterOp.EQ, value)]
            )
            if exclude_id is not None:
                stmt = stmt.where(Record.id != exclude_id)
            if exclude_group is not None:
                stmt = stmt.where(Record.translation_group != exclude_group)
            taken = (
                (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()
            )
        except QueryError as exc:
            if exc.reason != "reindexing":
                raise
            raise Conflict(
                f"{field.key!r} is being reindexed, so its uniqueness cannot be checked; "
                "writes to this type are refused until the rebuild completes"
            ) from exc
        if taken is not None:
            raise Conflict(f"{field.key!r} must be unique; {value!r} is already taken")


async def lock_type(db: AsyncSession, rtype: RecordType) -> None:
    """Serialise writes of one type — the mitigation design §7.8 names.

    The ``unique`` check is check-then-act, so two concurrent creates carrying
    the same value can both pass it. Taking the type row first makes the
    window empty: the second writer waits for the first to commit and then
    sees its index row.

    **Two statements, because a lock is a dialect feature and not a grammar
    one.** ``SELECT ... FOR UPDATE`` is the row lock on Postgres; on SQLite it
    compiles to a plain ``SELECT`` that locks nothing, and the reasoning that
    "the database is single-writer anyway" is where this went wrong. SQLite is
    single-*writer*, not single-*transaction*: a read-only transaction takes no
    lock at all, so eight concurrent creates each ran the check, each found the
    value free, and each then took the write lock in turn to insert. Eight
    201s, eight rows — measured. Issuing a write against the type row instead
    takes SQLite's ``RESERVED`` lock **at the top of the write path**, and
    ``RESERVED`` is exclusive among writers for the rest of the transaction, so
    the second writer blocks here rather than at its own ``INSERT`` — which is
    after its check. ``SET version = version`` is deliberately a no-op
    assignment: it must not bump the value any optimistic-concurrency caller is
    comparing against, and it must still be a write.

    This serialises every write to the type on SQLite, which is the trade §7.8
    describes and the README states. It is taken for every write rather than
    only for types with a ``unique`` field: the slug claim of §5 is the same
    check-then-act, and every type can have one.
    """
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(
            sa_update(RecordType)
            .where(RecordType.id == rtype.id)
            .values(version=RecordType.version)
        )
        return
    await db.execute(select(RecordType.id).where(RecordType.id == rtype.id).with_for_update())
