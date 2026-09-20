"""Health checks the module contributes. Design doc §8.9.

Two things degrade ``/health/ready`` here, and they are different failures.

A reindex orphaned by a worker restart is *recoverable* — the CLI finishes it —
but recoverable is not visible. A field that refuses filters with a 409 forever
because nothing ever ran the rebuild is noticed by whoever next tries that
filter, which turns a deploy detail into a support ticket. This degrades
``/health/ready`` instead, naming the type and the fields.

The second is ``reduce_drift``: a maintained aggregate (Phase 5 §5.2) that the
last verify found disagreeing with the records. Design §7.5's objection to a
maintained aggregate was exactly that it can drift, and the answer was that
drift would be *detectable* — which means nothing unless something says so out
loud. It is in-process state (:mod:`sm_records.index._drift`), so it reflects
verifies run by *this* process; a CLI verify runs in another one and reports on
its own stdout instead, which the README says.

The third is ``orphaned_locales``: records written in a language the install
has since dropped from ``content_locales``. Dropping one is **not** refused at
save — the records exist, and refusing the edit would make a typo unfixable —
so the public API stops serving them (``services.public``) and this is what
says how many there are and in which language. It is counted at
:meth:`~sm_records.module.RecordsModule.on_startup` and **only there**: the
framework's settings registry has no post-hydration hook to re-run it from
(``settings.registration`` records a class and nothing else), so an operator
who drops a locale sees the count at the next restart. The README says so, and
says how to list them meanwhile.

The check reads the database, which a ``register_health_checks`` hook cannot:
it runs before the lifespan opens one. So it reads what
:meth:`~sm_records.module.RecordsModule.on_startup` parked on the module
instance, and answers HEALTHY while that is absent — during boot there is
nothing to be stale yet, and a health check that fails because it ran early is
worse than no check at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from simple_module_core.health import HealthCheck, HealthCheckResult, HealthStatus
from sqlalchemy import func, select

from sm_records import locales
from sm_records.constants import REINDEX_ALL
from sm_records.index._drift import drift_detail
from sm_records.models import RecordType, table_sets
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings

if TYPE_CHECKING:
    from sm_records.module import RecordsModule

CHECK_NAME = "records.reindex"


def _age_seconds(raw: object, now: datetime) -> float | None:
    """Seconds since an ISO-8601 marker, or ``None`` if it cannot be read.

    An unparseable marker is treated as *not* stale rather than as infinitely
    stale: the column is plain JSON, a hand-edited or pre-Phase-3 value should
    not page anybody, and the rebuild it stands for is still enqueued.
    """
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=now.tzinfo)
    return (now - at).total_seconds()


def _entries(pending: object) -> dict[str, str]:
    """Tolerates the list shape written before Phase 3 — see
    :func:`sm_records.index.reindex.pending_map`. A marker with no instant is
    never stale; the rebuild it stands for is still enqueued."""
    if isinstance(pending, list):
        return {str(key): "" for key in pending}
    return dict(pending or {})


def _unique_keys(fields: object) -> set[str]:
    """The type's ``unique`` field keys, read straight from the stored JSON.

    A stale marker on one of them is worse than a slow filter: the uniqueness
    check of §7.8 is a query over the index, ``count_query`` refuses a pending
    field, and ``_claims.ensure_unique`` therefore turns *every* write to the
    type into a 409 until the rebuild finishes. That is worth saying out loud
    in the health detail rather than leaving an operator to discover it from a
    support ticket.
    """
    if not isinstance(fields, list):
        return set()
    return {
        str(field.get("key")) for field in fields if isinstance(field, dict) and field.get("unique")
    }


def _stale(rows, limit: int, now: datetime) -> tuple[list[str], bool]:
    """``(descriptions, any unique field affected)``."""
    out: list[str] = []
    blocked = False
    for key, pending, fields in rows:
        late = [
            field
            for field, at in _entries(pending).items()
            if (age := _age_seconds(at, now)) is not None and age > limit
        ]
        if late:
            if _unique_keys(fields) & set(late):
                blocked = True
            names = ", ".join("whole type" if f == REINDEX_ALL else f for f in sorted(late))
            out.append(f"{key} ({names})")
    return out, blocked


async def count_orphaned_locales(db_state, settings: RecordsSettings) -> dict[str, int]:
    """``{locale: records}`` for every locale outside ``content_locales``.

    One ``GROUP BY locale`` per table set (Phase 5 §6.3) — a collection's
    records live in its own document table — over live rows only: a trashed
    record is not reachable anywhere, so counting it would report work an
    operator cannot see. Run once, at startup; see the module docstring.
    """
    known = {locale.lower() for locale in locales.supported(settings)}
    out: dict[str, int] = {}
    async with db_state.session_factory() as session:
        for tables in table_sets():
            cls = tables.record
            rows = (
                await session.execute(select(cls.locale, func.count(cls.id)).group_by(cls.locale))
            ).all()
            for locale, count in rows:
                if str(locale).lower() not in known:
                    out[str(locale)] = out.get(str(locale), 0) + int(count)
    return dict(sorted(out.items()))


def _orphaned_detail(counts: dict[str, int]) -> str:
    listed = ", ".join(f"{locale}: {count}" for locale, count in counts.items())
    return (
        f"orphaned_locales: {{{listed}}} — records in a language this install no longer "
        "publishes; they are hidden from the public API and still editable in the admin "
        "(filter=locale:eq:<tag>)"
    )


def stale_reindex_check(module: RecordsModule) -> HealthCheck:
    async def check() -> HealthCheckResult:
        db_state = getattr(module, "db", None)
        if db_state is None:
            return HealthCheckResult(status=HealthStatus.HEALTHY)
        settings = getattr(module, "settings", None) or RecordsSettings()
        limit = settings.reindex_stale_after_seconds
        now = utcnow()
        async with db_state.session_factory() as session:
            rows = (
                await session.execute(
                    select(RecordType.key, RecordType.reindex_pending, RecordType.fields)
                )
            ).all()
        stale, blocked = _stale(rows, limit, now)
        details: list[str] = []
        if stale:
            detail = (
                f"reindex pending for longer than {limit}s: {'; '.join(stale)} — "
                "run `python -m sm_records.cli reindex`"
            )
            if blocked:
                detail += (
                    "; a unique field is among them, so writes to this type are refused "
                    "until the rebuild completes"
                )
            details.append(detail)
        # Reported alongside rather than instead: a stale rebuild and a drifted
        # aggregate are different faults with different fixes, and a check that
        # showed only the first would hide the second for as long as any type
        # had a marker set.
        drift = drift_detail()
        if drift is not None:
            details.append(drift)
        # Counted at startup and parked on the instance: see the module
        # docstring for why it is not recounted on a settings edit.
        orphaned = getattr(module, "orphaned_locales", None)
        if orphaned:
            details.append(_orphaned_detail(orphaned))
        if not details:
            return HealthCheckResult(status=HealthStatus.HEALTHY)
        return HealthCheckResult(status=HealthStatus.DEGRADED, detail="; ".join(details))

    return HealthCheck(name=CHECK_NAME, check=check)
