"""The per-tenant counts behind :mod:`sm_records.health`'s details.

Split from that module for the 300-line cap. The seam: this file counts rows
and says what each count means, and ``health`` decides when to report them.
Every read here goes through :func:`sm_records._cross_tenant.read_all`, so
the counts cover every tenant, whatever the caller has bound (tenancy design
§A.5).
"""

from __future__ import annotations

from sqlalchemy import func, select

from sm_records import locales
from sm_records._cross_tenant import read_all, tenant_counts
from sm_records.models import table_sets
from sm_records.settings import RecordsSettings
from sm_records.tenancy import DEFAULT_TENANT

__all__ = [
    "count_invalid_records",
    "count_orphaned_locales",
    "invalid_detail",
    "orphaned_detail",
    "outside_default",
]


async def count_orphaned_locales(db_state, settings: RecordsSettings) -> dict[str, int]:
    """``{"tenant/locale": records}`` for every locale outside ``content_locales``.

    One ``GROUP BY tenant_id, locale`` per table set (Phase 5 §6.3) — a
    collection's records live in its own document table — over live rows only:
    a trashed record is not reachable anywhere, so counting it would report
    work an operator cannot see. ``content_locales`` is one setting for the
    whole install, and the tenant is in the key so an operator knows whose
    records to look at. Run once, at startup; see :mod:`sm_records.health`.
    """
    known = {locale.lower() for locale in locales.supported(settings)}
    out: dict[str, int] = {}
    async with db_state.session_factory() as session:
        for tables in table_sets():
            cls = tables.record
            stmt = select(cls.tenant_id, cls.locale, func.count(cls.id)).group_by(
                cls.tenant_id, cls.locale
            )
            for tenant, locale, count in (await read_all(session, stmt)).all():
                if str(locale).lower() not in known:
                    key = f"{tenant}/{locale}"
                    out[key] = out.get(key, 0) + int(count)
    return dict(sorted(out.items()))


def _tenants(keys) -> int:
    return len({key.split("/", 1)[0] for key in keys})


def orphaned_detail(counts: dict[str, int], *, named: bool = True) -> str:
    """``named=False`` is the multi-mode form: counts only, no tenant and no
    language tag (:mod:`sm_records.health`, review M2)."""
    if named:
        listed = "{" + ", ".join(f"{locale}: {count}" for locale, count in counts.items()) + "}"
    else:
        listed = f"{sum(counts.values())} record(s) across {_tenants(counts)} tenant(s)"
    return (
        f"orphaned_locales: {listed} — records in a language this install no longer "
        "publishes; they are hidden from the public API and still editable in the admin "
        "(filter=locale:eq:<tag>)"
    )


async def count_invalid_records(session) -> dict[str, int]:
    """``{tenant: records}`` carrying a stored invalid mark, live only, across
    table sets and tenants.

    One statement per table set — a collection's records live in its own
    document table (Phase 5 §6.3) — grouped by tenant. Each is an index range
    rather than a scan: both backends answer ``invalid_since IS NOT NULL``
    from the column's own index by reading only the entries that have a
    value, so the cost is proportional to how many records are marked, and
    that is what makes it affordable per check.
    """
    out: dict[str, int] = {}
    for tables in table_sets():
        cls = tables.record
        stmt = (
            select(cls.tenant_id, func.count(cls.id))
            .where(cls.invalid_since.isnot(None))
            .group_by(cls.tenant_id)
        )
        for tenant, count in (await read_all(session, stmt)).all():
            out[str(tenant)] = out.get(str(tenant), 0) + int(count)
    return dict(sorted(out.items()))


def invalid_detail(counts: dict[str, int], *, named: bool = True) -> str:
    """``named=False`` is the multi-mode form: the total and how many tenants,
    never which (:mod:`sm_records.health`, review M2)."""
    if named:
        per_tenant = "(" + ", ".join(f"{t}: {count}" for t, count in counts.items()) + ")"
    else:
        per_tenant = f"across {len(counts)} tenant(s)"
    return (
        f"invalid_records: {sum(counts.values())} {per_tenant} — record(s) marked as not "
        "satisfying their type's schema, from a forced schema change; each one's next save "
        "clears the mark (filter=invalid:eq:true)"
    )


async def outside_default(session, tenants: set[str]) -> str | None:
    """The single-mode detail: what sits in tenants this host never serves."""
    foreign = tenants - {DEFAULT_TENANT}
    if not foreign:
        return None
    counts = await tenant_counts(session, foreign)
    listed = ", ".join(
        f"{tenant}: {c.types} type(s), {c.records + c.trashed} record(s)"
        for tenant, c in counts.items()
    )
    return (
        f"tenants_outside_default: {{{listed}}} — this host is single-tenant and serves only "
        f"{DEFAULT_TENANT!r}; these rows are untouched but unreachable "
        "(`python -m sm_records.cli tenants`)"
    )
