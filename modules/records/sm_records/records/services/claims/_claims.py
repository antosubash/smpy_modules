"""The two claims a record write makes that no database constraint can hold,
and the lock that makes them hold anyway.

The ``unique`` rule of design §7.8 and the slug rule of §5 are both
*check-then-act*: a ``SELECT`` inside the write's transaction, then an
``INSERT`` that assumes the answer is still true. Neither can be a constraint
the database enforces on its own — the index tables are shared across every
field of a kind, so a unique index naming a runtime-chosen field key is not
expressible — so what closes the window is
:func:`~sm_records.records.services._lock.lock_type` — re-exported here, and split
into its own module for the file cap — and what catches the one case the
database *can* express is :func:`flush_write`.

Split out of :mod:`sm_records.records.services._payload` for the file cap, along the
seam that was already there: that module is "what the write does to the
payload", and this one is "what the write claims about the rest of the type".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core._text import NUL_PROBLEM, has_nul
from sm_records.core.tenancy import bound_tenant
from sm_records.models import RecordType, tables_for
from sm_records.records.services._lock import lock_type
from sm_records.records.services.claims._unique_claims import ensure_unique, taken_by
from sm_records.records.services.claims._uuids import uuid_taken
from sm_records.records.services.errors import Conflict, ValidationFailed

__all__ = ["ensure_slug_free", "ensure_unique", "flush_write", "lock_type", "taken_by"]


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
    translation group — :attr:`~sm_records.models.TableSet.group_locale_signatures`.

    Reached by a writer that sets ``translation_group`` itself: an import
    carrying the column, or a second ``POST /translations`` that lost the race
    with the first. The endpoint's own check answers the ordinary case; this is
    what keeps the race a 409 rather than a 500.

    Naming the type is only honest because the index is scoped by ``type_id``
    (migration ``fe3ea2dfe0fb``). While it was not, this sentence could be
    raised by a collision with a record of some *other* type, and then named a
    record of this one that does not exist.
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
    # Before the lookup, not after: the slug is a bound parameter against a
    # ``text`` column, so a NUL in it is a driver-level failure — a 500 — and
    # not a slug that is merely free. Every caller inside this module arrives
    # through ``_payload.slug_for``, whose slugifier already strips the
    # character; this is the rule stated where the value meets the column, for
    # a caller that does not.
    if has_nul(slug):
        raise ValidationFailed(f"slug {NUL_PROBLEM}", [{"field": "slug", "message": NUL_PROBLEM}])
    record = tables_for(rtype).record
    stmt = select(record.id).where(
        record.type_id == rtype.id,
        record.locale == locale,
        record.slug == slug,
        record.tenant_id == bound_tenant(),  # a natural-key lookup: tenancy §E
    )
    if exclude_id is not None:
        stmt = stmt.where(record.id != exclude_id)
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

    Recognised by the type's own :class:`~sm_records.models.TableSet`, which
    carries both signature pairs — a collection's indexes are named after *its*
    tables, so the global spellings would not match its refusals and every lost
    slug race inside a collection would be a 500 again (Phase 5 §6.3). Anything
    matching neither is re-raised, because an ``IntegrityError`` this module
    cannot explain is a bug rather than a 409.

    ``rtype.key`` is read **before** the flush. A flush that raises expires
    every instance in the session, so reading it afterwards would emit a
    refresh on a transaction that now accepts nothing but a rollback.
    """
    type_key = rtype.key
    tables = tables_for(rtype)
    try:
        await db.flush()
    except IntegrityError as exc:
        message = str(exc.orig or exc)
        if uuid_taken(tables, exc):
            raise Conflict(f"another {type_key} record already uses that uuid") from exc
        if any(sig in message for sig in tables.group_locale_signatures):
            raise _group_locale_taken(type_key, locale) from exc
        if slug is None or not any(sig in message for sig in tables.slug_signatures):
            raise
        raise _slug_taken(type_key, slug, locale) from exc
