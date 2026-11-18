"""Records of a type that have a date in a window, for a calendar in another module.

Events' ``records:dates`` source puts these on a calendar without importing a table: what
crosses the boundary is plain frozen data (:class:`DatedHit`).

**Access is records' own, never wider.** A person (:class:`DatedCaller`) needs ``records.view``
and must pass the type's ``allowed_roles`` (widened by a ``records.type.<key>`` grant; the admin
wildcard widens nothing), as for the list API. ``caller=None`` is the public: only a type that is
``is_public``. A type the caller may not read, an unknown type and an unknown field are all an
**empty page**, so nothing can be probed. Only **published**, untrashed records are returned,
never a draft, to anyone.

**Tenant.** The caller names it; it is validated, bound with records' ``tenant_scope`` and pinned
again as a predicate on every statement.

**Bounds.** ``limit`` is an ``int`` from 1 to :data:`MAX_DATED_BATCH` (``bool`` and anything else
is a ``ValueError``), and the window is at most ``MAX_DATED_WINDOW_DAYS`` long. Ascending by the
field; ``truncated`` says there was more.

**Fields.** A field must be indexed and of kind ``date`` or ``datetime``; the window's bounds
are of that kind (``date`` for a date field, aware ``datetime`` for a datetime one), else
:class:`DatedQueryError`. On a ``translatable`` type, only ``locale`` is returned when one is
given; otherwise every row. Never commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, Literal

from simple_module_db import is_valid_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_records.contracts._dated_access import DatedCaller, may_read
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import RecordStatus, RecordType, tables_for
from sm_records.records.index._coerce import coerce_date, coerce_datetime
from sm_records.records.index._fields import declared_keys, indexed_map
from sm_records.records.index.query import Filter, QueryError, Sort
from sm_records.records.services._listing import page_of
from sm_records.schema.types import IndexKind

__all__ = [
    "MAX_DATED_BATCH",
    "DatedCaller",
    "DatedHit",
    "DatedPage",
    "DatedQueryError",
    "DatedTypeInfo",
    "dated_field_kind",
    "dated_records",
    "dated_types",
]

MAX_DATED_BATCH: Final = 1000
MAX_DATED_WINDOW_DAYS: Final = 800
_SETTINGS: Final = RecordsSettings(max_page_size=MAX_DATED_BATCH + 1)
Kind = Literal["date", "datetime"]
Reason = Literal["not_a_date", "not_indexed", "reindexing", "kind_mismatch"]
_KINDS: Final = {IndexKind.DATE: "date", IndexKind.DATETIME: "datetime"}


class DatedQueryError(ValueError):
    """The field cannot be asked for as a date range."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class DatedHit:
    uuid: str
    type_key: str
    locale: str
    display_title: str
    start: date | datetime
    end: date | datetime | None


@dataclass(frozen=True)
class DatedPage:
    hits: list[DatedHit]
    truncated: bool


@dataclass(frozen=True)
class DatedTypeInfo:
    key: str
    label: str
    is_public: bool
    fields: list[tuple[str, str, Kind]]
    """``(key, label, kind)`` of each indexed date or datetime field."""


def _tenant(tenant_id: object) -> str:
    if not isinstance(tenant_id, str) or not is_valid_tenant_id(tenant_id):
        raise ValueError(f"not a valid tenant id: {tenant_id!r}")
    return tenant_id


def _limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_DATED_BATCH:
        raise ValueError(f"limit must be an int from 1 to {MAX_DATED_BATCH}")
    return limit


def _is_aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _bound_ok(kind: str, value: object) -> bool:
    if kind == "date":
        return isinstance(value, date) and not isinstance(value, datetime)
    return _is_aware(value)


def _kind_of(rtype: RecordType, name: str) -> str:
    """The kind of a field that must be an indexed date or datetime."""
    if name not in declared_keys(list(rtype.fields or [])):
        raise DatedQueryError("not_indexed")
    indexed = indexed_map(list(rtype.fields or []))
    if name not in indexed:
        raise DatedQueryError("not_indexed")
    kind = _KINDS.get(indexed[name].kind)
    if kind is None:
        raise DatedQueryError("not_a_date")
    return kind


def _value(raw: Any, kind: str) -> date | datetime | None:
    return coerce_date(raw) if kind == "date" else coerce_datetime(raw)


async def _type(db: AsyncSession, tenant: str, key: str) -> RecordType | None:
    stmt = select(RecordType).where(col(RecordType.key) == key, col(RecordType.tenant_id) == tenant)
    return (await db.execute(stmt)).scalars().first()


async def dated_records(
    session: AsyncSession,
    *,
    tenant_id: str,
    type_key: str,
    field: str,
    end_field: str | None = None,
    lo: date | datetime,
    hi: date | datetime,
    caller: DatedCaller | None,
    locale: str | None,
    limit: int,
) -> DatedPage:
    """Published records of ``type_key`` whose ``field`` lies in ``[lo, hi)``, ascending by it,
    at most ``limit``. See the module docstring for who gets what."""
    tenant, size = _tenant(tenant_id), _limit(limit)
    if hi <= lo or (hi - lo) > timedelta(days=MAX_DATED_WINDOW_DAYS):  # type: ignore[operator]
        raise ValueError("the window must be positive and at most 800 days")
    with tenant_scope(tenant):
        rtype = await _type(session, tenant, type_key)
        if rtype is None or not may_read(rtype, caller):
            return DatedPage([], False)
        if field not in declared_keys(list(rtype.fields or [])):
            return DatedPage([], False)
        kind = _kind_of(rtype, field)
        if end_field is not None and _kind_of(rtype, end_field) != kind:
            raise DatedQueryError("kind_mismatch")
        if not (_bound_ok(kind, lo) and _bound_ok(kind, hi)):
            raise DatedQueryError("kind_mismatch")
        record = tables_for(rtype).record

        def narrow(stmt: Any) -> Any:
            stmt = stmt.where(record.status == RecordStatus.PUBLISHED, record.tenant_id == tenant)
            if rtype.translatable and locale is not None:
                stmt = stmt.where(record.locale == locale)
            return stmt

        try:
            found = await page_of(
                session,
                rtype,
                settings=_SETTINGS,
                filters=[Filter(field, _gte(), lo), Filter(field, _lt(), hi)],
                sorts=[Sort(field)],
                page=1,
                page_size=size + 1,
                after=None,
                with_total=False,
                narrow=narrow,
            )
        except QueryError as exc:
            raise DatedQueryError(
                "reindexing" if exc.reason == "reindexing" else "not_indexed"
            ) from exc
    hits: list[DatedHit] = []
    for row in found.items[:size]:
        data = row.data or {}
        start = _value(data.get(field), kind)
        if start is None:  # a value the index took but the payload cannot read back
            continue
        end = _value(data.get(end_field), kind) if end_field else None
        hits.append(
            DatedHit(
                uuid=row.uuid,
                type_key=rtype.key,
                locale=row.locale,
                display_title=row.display_title or "",
                start=start,
                end=end,
            )
        )
    return DatedPage(hits, len(found.items) > size)


def _gte() -> Any:
    from sm_records.records.index._predicates import FilterOp

    return FilterOp.GTE


def _lt() -> Any:
    from sm_records.records.index._predicates import FilterOp

    return FilterOp.LT


async def dated_field_kind(
    session: AsyncSession, *, tenant_id: str, type_key: str, field: str, caller: DatedCaller | None
) -> Kind | None:
    """``"date"`` or ``"datetime"`` for an indexed date field of a type ``caller`` may read, else
    ``None`` (an unknown type, one they may not read and a field that is not such a date are the
    same answer). For choosing the window a source asks for."""
    tenant = _tenant(tenant_id)
    with tenant_scope(tenant):
        rtype = await _type(session, tenant, type_key)
        if rtype is None or not may_read(rtype, caller):
            return None
        found = indexed_map(list(rtype.fields or [])).get(field)
        return _KINDS.get(found.kind) if found else None  # type: ignore[return-value]


async def dated_types(
    session: AsyncSession, *, tenant_id: str, caller: DatedCaller
) -> list[DatedTypeInfo]:
    """The types ``caller`` may read that have an indexed date or datetime field, with those
    fields, by key. For validating a source's settings."""
    tenant = _tenant(tenant_id)
    out: list[DatedTypeInfo] = []
    with tenant_scope(tenant):
        stmt = (
            select(RecordType)
            .where(col(RecordType.tenant_id) == tenant)
            .order_by(col(RecordType.key))
        )
        for rtype in (await session.execute(stmt)).scalars().all():
            if not may_read(rtype, caller):
                continue
            indexed = indexed_map(list(rtype.fields or []))
            fields: list[tuple[str, str, Kind]] = []
            for raw in rtype.fields or []:
                found = indexed.get(str(raw.get("key")))
                kind = _KINDS.get(found.kind) if found else None
                if kind:
                    fields.append((str(raw["key"]), str(raw.get("label") or raw["key"]), kind))  # type: ignore[arg-type]
            if fields:
                out.append(DatedTypeInfo(rtype.key, rtype.label, bool(rtype.is_public), fields))
    return out
