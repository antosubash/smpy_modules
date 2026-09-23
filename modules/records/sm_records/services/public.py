"""Reading published records as nobody in particular (design §10).

Three differences from the admin read, and each of them is a rule rather than
a convenience:

* **A type that is not ``is_public`` is indistinguishable from one that does
  not exist.** Same status, same body, whether the caller asked by key or by
  uuid. A 403 on a private type would turn the endpoint into an oracle for
  "which type keys exist on this install", which is exactly the enumeration
  an anonymous surface must not offer.
* **One language at a time.** ``?locale=`` names it and its *absence* means
  the default content locale, never "all" — an anonymous reader is asking for
  one site, and merging languages into one list is how a German record gets
  served to an English reader (Phase 5 §4.4). The by-uuid read is the
  exception and is locale-blind: a uuid is one record.
* **Published only, and never the trash.** ``status`` is a predicate on the
  query, not a filter the caller could drop; the soft-delete filter is the
  framework's and applies as everywhere else.
* **No ``expand``.** Not a parameter that was forgotten: §10 refuses to let an
  anonymous caller turn one request into a batch of joins against other types,
  some of which are not public.

The filter and sort grammar is the admin one **narrowed to the public shape**.
Refusing a field the index cannot answer is ``index.query``'s job and this adds
nothing to it; what this adds is an **allow-list** — the type's declared field
keys plus ``slug``, ``display_title`` and ``published_at``, i.e. exactly what
``contracts.public`` publishes (:func:`_check_columns`). Everything else is a
400 naming the field: the fixed columns the public shape drops (``status``,
``position``, ``created_at``, ``updated_at``), which would otherwise let an
anonymous caller binary-search a timestamp it cannot read, and a **virtual
field** an index provider projects, whose value is not in the payload at all
and which ``?after=`` would hand back in clear inside the cursor.

What the *endpoint* does with the refusal differs (§10: 400 naming the field,
never the admin's 409), and that mapping lives in ``endpoints/api/public.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import locales
from sm_records._text import has_nul
from sm_records.index._fields import declared_keys
from sm_records.index._fixed import PUBLIC_FIXED_COLUMNS
from sm_records.index.query import (
    Filter,
    QueryError,
    Sort,
    bounded_count_query,
    decode_cursor,
    encode_cursor,
    page_query,
    sort_plan,
    sort_signature,
)
from sm_records.models import Record, RecordStatus, RecordType, tables_for
from sm_records.services._listing import RecordListPage
from sm_records.services._translations import published_siblings
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings
from sm_records.tenancy import bound_tenant

__all__ = [
    "NOT_FOUND",
    "get_public_record",
    "get_public_type",
    "list_public_records",
    "published_siblings",
]

NOT_FOUND: Final = "not found"
"""The one 404 body this whole surface ever produces.

Deliberately uninformative and deliberately *identical* everywhere: a missing
type, a private type, a draft record, a trashed record and an unknown uuid all
answer with this. A caller who can tell the five apart can enumerate private
content by its absence (§10).
"""


def _published(record: Any):
    """ "published", against one table set's document class.

    A function since Phase 5 §6.3 rather than the module-level predicate it was:
    a public collection type's rows are in that collection's table, and a bound
    column from the global class would name a table the statement does not
    have."""
    return record.status == RecordStatus.PUBLISHED


def _published_only(record: Any, stmt):
    """The one predicate this whole surface is defined by. Bound to a document
    class it becomes the shape ``bounded_count_query``'s ``narrow`` takes, so
    the page and both halves of its count cannot disagree about what "public"
    means.

    **And in the bound tenant, said explicitly** (tenancy design §E): this is
    the anonymous surface, where a row from the wrong tenant would be an
    enumeration oracle, so it does not rest on the framework's loader criteria
    alone."""
    return stmt.where(_published(record), record.tenant_id == bound_tenant())


def _narrow_for(record: Any, locale: str):
    """``_published_only`` plus "and in this language".

    One callable so the page and both halves of its bounded count cannot
    disagree about what this listing contains — the same reason
    :func:`_published_only` exists on its own.
    """

    def narrow(stmt):
        return _published_only(record, stmt).where(record.locale == locale)

    return narrow


def _check_columns(rtype: RecordType, filters: Sequence[Filter], sorts: Sequence[Sort]) -> None:
    """Refuse a filter or sort naming anything outside the public shape.

    **An allow-list, not a deny-list.** It used to subtract the hidden fixed
    columns from the full set and let everything else through to
    ``index._filters.resolve``, which resolves a **virtual field** — a key an
    index provider projects (§7.6) — exactly as it resolves a declared one. A
    declared field's value is in ``data`` and therefore already public; a
    virtual field's is nowhere in ``PublicRecordRead``. So an anonymous caller
    could filter on a host-computed score it cannot read, sort by it, and get
    the value back **in clear** inside the ``?after=`` cursor, which carries
    the resolved sort values. That is verbatim the argument
    ``_fixed.PUBLIC_FIXED_COLUMNS`` gives for removing ``created_at`` and
    ``position``, applied to a column the host rather than the module invented.

    What is allowed is therefore exactly what the response shape carries: the
    type's **declared** field keys, plus ``slug``, ``display_title`` and
    ``published_at``. A declared-but-unindexed field still falls through to the
    grammar's own ``not_indexed`` refusal, because "you cannot query that" is
    the honest answer and the endpoint flattens both into one 400 anyway.
    Reduce-spec keys are refused here for the same reason virtual fields are.

    ``QueryError`` with the ``unknown`` reason ``index.query`` gives a key no
    type declares — the endpoint flattens every reason into one 400 naming the
    field (§10), so a hidden column, a virtual field and a typo are the same
    sentence to a caller who cannot see the schema.
    """
    allowed = declared_keys(list(rtype.fields or [])) | PUBLIC_FIXED_COLUMNS
    for name in [flt.field for flt in filters] + [sort.field for sort in sorts]:
        if name not in allowed:
            raise QueryError(name, "unknown", f"{name!r} is not a field of {rtype.key!r}")


async def get_public_type(db: AsyncSession, key: str) -> RecordType:
    """The type, if it exists *and* is public. Otherwise the shared 404."""
    if has_nul(key):
        # Never a bound parameter: the driver refuses ``\x00`` in one, and
        # this is the surface where that was a 500 to a caller with no session
        # at all. No stored key can contain one, so the shared 404 is exact.
        raise NotFound(NOT_FOUND)
    stmt = select(RecordType).where(RecordType.key == key, RecordType.tenant_id == bound_tenant())
    rtype = (await db.execute(stmt)).scalars().first()
    if rtype is None or not rtype.is_public:
        raise NotFound(NOT_FOUND)
    return rtype


async def get_public_record(
    db: AsyncSession, rtype: RecordType, uuid: str, *, settings: RecordsSettings
) -> Record:
    """One published record of a public type, by uuid.

    The ``status`` predicate is in the statement rather than checked after the
    load: a draft and a nonexistent uuid have to be the same 404, and a check
    after the fact is one refactor away from leaking the difference in a log
    line or a timing.

    **And in a language this site still publishes.** Dropping a locale from
    ``content_locales`` is not guarded at save (there is no good answer: the
    records exist, and refusing the edit would make a typo unfixable), so the
    records written in it stay. What they must not do is stay *publicly
    readable* — a language the listing refuses to name (``?locale=de`` is a
    400 once ``de`` is gone) cannot go on being served by uuid, or the site
    publishes in a language it says it does not. The admin API is deliberately
    the other way: an operator has to be able to read, edit and re-home them.
    """
    cls = tables_for(rtype).record
    stmt = _published_only(
        cls,
        select(cls).where(
            cls.uuid == uuid,
            cls.type_id == rtype.id,
            cls.locale.in_(locales.supported(settings)),
        ),
    )
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(NOT_FOUND)
    return record


async def list_public_records(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    locale: str,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    page: int = 1,
    page_size: int | None = None,
    after: str | None = None,
    with_total: bool = True,
) -> RecordListPage:
    """One page of a public type's published records, and the matching total.

    ``QueryError`` from the builder — or from :func:`_check_columns`, which
    runs first — propagates: the endpoint turns every reason into the same 400
    naming the field, because "not indexed", "being reindexed" and "not part
    of the public shape" are the same answer to someone who cannot see the
    schema (§10). ``CursorError`` is flattened to a 400 there too.

    ``locale`` is **required and single-valued**, and the endpoint defaults it
    to ``default_content_locale`` rather than leaving it off (§4.4): an
    anonymous reader asks for one site, so "no locale" cannot mean "every
    language merged into one list". It is applied as a predicate on the
    statement and not as a caller ``Filter``, for two reasons — ``locale`` is
    not in :data:`PUBLIC_FIXED_COLUMNS`, so :func:`_check_columns` refuses it
    from a caller; and narrowing both halves of the bounded count is what a
    ``narrow`` callable is for, exactly as with the published predicate.

    The bound on ``total`` (F4), the ``?after=`` cursor (F11) and
    ``total=false`` are the admin listing's, unchanged — an anonymous caller
    walking a large public type is exactly who wants them. The published
    predicate narrows **both** halves of the bounded count, for the reason
    ``bounded_count_query`` gives: a bound whose inner ``LIMIT`` fills with
    rows the outer then discards under-counts near the cap.
    """
    _check_columns(rtype, filters, sorts)
    narrow = _narrow_for(tables_for(rtype).record, locale)
    size = settings.clamp_page_size(page_size)
    fields = list(rtype.fields or [])
    # ``locale`` is in the signature because it is a predicate on the statement
    # rather than one of the caller's filters (:func:`_narrow_for`): without it
    # a cursor minted under ``?locale=en`` was accepted under ``?locale=de``,
    # which is "resume after this row" spoken about a different listing. The
    # terms' kinds are in it for the reason ``index._cursor`` gives.
    plan = sort_plan(rtype, fields, sorts)
    signature = sort_signature(rtype.key, sorts, locale=locale, terms=plan)
    decoded = decode_cursor(after, signature, plan) if after else None

    total: int | None = None
    capped = False
    if with_total:
        cap = settings.max_count
        counted = int(
            (
                await db.execute(
                    bounded_count_query(rtype, fields, filters, cap=cap, narrow=narrow)
                )
            ).scalar_one()
        )
        capped = counted > cap
        total = cap if capped else counted

    stmt, terms = page_query(rtype, fields, filters, sorts, after=decoded)
    stmt = narrow(stmt)
    if decoded is None:
        stmt = stmt.offset(max(page - 1, 0) * size)
    rows = (await db.execute(stmt.limit(size))).all()
    items = [row[0] for row in rows]
    next_cursor = (
        encode_cursor(signature, [*rows[-1][1 : len(terms) + 1], items[-1].id])
        if len(rows) == size
        else None
    )
    return RecordListPage(items, total, capped, next_cursor)
