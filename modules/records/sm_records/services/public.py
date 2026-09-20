"""Reading published records as nobody in particular (design §10).

Three differences from the admin read, and each of them is a rule rather than
a convenience:

* **A type that is not ``is_public`` is indistinguishable from one that does
  not exist.** Same status, same body, whether the caller asked by key or by
  uuid. A 403 on a private type would turn the endpoint into an oracle for
  "which type keys exist on this install", which is exactly the enumeration
  an anonymous surface must not offer.
* **Published only, and never the trash.** ``status`` is a predicate on the
  query, not a filter the caller could drop; the soft-delete filter is the
  framework's and applies as everywhere else.
* **No ``expand``.** Not a parameter that was forgotten: §10 refuses to let an
  anonymous caller turn one request into a batch of joins against other types,
  some of which are not public.

The filter and sort grammar is the admin one **narrowed to the public shape**.
Refusing a field the index cannot answer is ``index.query``'s job and this adds
nothing to it; what this adds is an allow-list over the *fixed* columns, which
are queryable on every type whatever it declares. ``status``, ``position``,
``created_at`` and ``updated_at`` are removed from the response shape
(``contracts.public``) and would otherwise still answer a filter — an
anonymous caller can binary-search a timestamp it cannot read. They are
refused by name instead, exactly as an unindexed field is.

What the *endpoint* does with the refusal differs (§10: 400 naming the field,
never the admin's 409), and that mapping lives in ``endpoints/api/public.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index._fixed import FIXED_COLUMNS, PUBLIC_FIXED_COLUMNS
from sm_records.index.query import Filter, QueryError, Sort, build_query, count_query
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.services.errors import NotFound
from sm_records.settings import RecordsSettings

__all__ = ["NOT_FOUND", "get_public_record", "get_public_type", "list_public_records"]

NOT_FOUND: Final = "not found"
"""The one 404 body this whole surface ever produces.

Deliberately uninformative and deliberately *identical* everywhere: a missing
type, a private type, a draft record, a trashed record and an unknown uuid all
answer with this. A caller who can tell the five apart can enumerate private
content by its absence (§10).
"""

_PUBLISHED = Record.status == RecordStatus.PUBLISHED

_HIDDEN_COLUMNS: Final[frozenset[str]] = FIXED_COLUMNS - PUBLIC_FIXED_COLUMNS
"""Fixed columns this surface will not answer about — the projection every
record has, minus the part the public shape publishes."""


def _check_columns(rtype: RecordType, filters: Sequence[Filter], sorts: Sequence[Sort]) -> None:
    """Refuse a filter or sort naming a column the public shape removes.

    ``QueryError`` with the same ``unknown`` reason ``index.query._resolve``
    gives a key no type declares — the endpoint flattens every reason into one
    400 naming the field (§10), and these columns have to be indistinguishable
    from a field that simply is not there. A declared field can never be
    keyed after one of them (``constants.RESERVED_FIELD_KEYS``), so this
    refuses nothing a type could have meant.
    """
    for name in [flt.field for flt in filters] + [sort.field for sort in sorts]:
        if name in _HIDDEN_COLUMNS:
            raise QueryError(name, "unknown", f"{name!r} is not a field of {rtype.key!r}")


async def get_public_type(db: AsyncSession, key: str) -> RecordType:
    """The type, if it exists *and* is public. Otherwise the shared 404."""
    rtype = (await db.execute(select(RecordType).where(RecordType.key == key))).scalars().first()
    if rtype is None or not rtype.is_public:
        raise NotFound(NOT_FOUND)
    return rtype


async def get_public_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    """One published record of a public type, by uuid.

    The ``status`` predicate is in the statement rather than checked after the
    load: a draft and a nonexistent uuid have to be the same 404, and a check
    after the fact is one refactor away from leaking the difference in a log
    line or a timing.
    """
    stmt = select(Record).where(Record.uuid == uuid, Record.type_id == rtype.id, _PUBLISHED)
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(NOT_FOUND)
    return record


async def list_public_records(
    db: AsyncSession,
    rtype: RecordType,
    *,
    settings: RecordsSettings,
    filters: Sequence[Filter] = (),
    sorts: Sequence[Sort] = (),
    page: int = 1,
    page_size: int | None = None,
) -> tuple[list[Record], int]:
    """One page of a public type's published records, and the matching total.

    ``QueryError`` from the builder — or from :func:`_check_columns`, which
    runs first — propagates: the endpoint turns every reason into the same 400
    naming the field, because "not indexed", "being reindexed" and "not part
    of the public shape" are the same answer to someone who cannot see the
    schema (§10).
    """
    _check_columns(rtype, filters, sorts)
    size = settings.clamp_page_size(page_size)
    offset = max(page - 1, 0) * size
    fields = list(rtype.fields or [])
    count_stmt = count_query(rtype, fields, filters).where(_PUBLISHED)
    stmt = build_query(rtype, fields, filters, sorts).where(_PUBLISHED).offset(offset).limit(size)
    total = int((await db.execute(count_stmt)).scalar_one())
    return list((await db.execute(stmt)).scalars().all()), total
