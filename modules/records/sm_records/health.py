"""Health checks the module contributes. Design doc §8.9.

Four things degrade ``/health/ready`` here, and they are different failures.

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

The third is ``invalid_records``: records carrying a stored ``invalid_since``
mark (§8.3, :mod:`sm_records.services._invalid`) — content a forced schema
change left behind, which is still served, still editable and satisfies
nobody's schema. Counted from the column on every check rather than scanned:
both backends answer ``invalid_since IS NOT NULL`` from that column's own
index by reading only the entries that have a value, so the cost is
proportional to how many records are marked. It is *not* an error — forcing a
change is a decision an operator made on purpose — but an install that has
carried the same twelve marked records for a month has forgotten about them,
and the health detail is where that becomes visible.

The fourth is ``orphaned_locales``: records written in a language the install
has since dropped from ``content_locales``. Dropping one is **not** refused at
save — the records exist, and refusing the edit would make a typo unfixable —
so the public API stops serving them (``services.public``) and this is what
says how many there are and in which language. It is counted at
:meth:`~sm_records.module.RecordsModule.on_startup` and **only there**: the
framework's settings registry has no post-hydration hook to re-run it from
(``settings.registration`` records a class and nothing else), so an operator
who drops a locale sees the count at the next restart. The README says so, and
says how to list them meanwhile.

**Every read here is across tenants** (tenancy design §A.5), through
:func:`sm_records._cross_tenant.read_all`. On a multi-tenant host the check
runs inside ``TenantMiddleware``, which binds whatever tenant a header names,
and that binding must not narrow what the check reports.

**What the detail may say depends on the mode.** ``/health/ready`` is mounted
without auth. On a **single-tenant** host the detail names each type as
``tenant/key`` with its fields, each orphaned locale as ``tenant/locale``, and
the invalid count per tenant — there is one organisation, and the names are
what an operator needs to find the rows. On a **multi-tenant** host that same
sentence would tell any anonymous caller which tenants exist and what their
types and fields are called — the cross-tenant oracle the isolation rules out
everywhere else (review M2). So there the detail carries **counts only**
("2 type(s) across 2 tenant(s)", "invalid_records: 1"), and the named sentence
goes to this module's logger at INFO, once per change of wording rather than
on every poll, where only an operator reads it.

A fifth detail exists on a **single-tenant** host only: ``tenants_outside_default``.
Such a host serves only ``default``. Rows in any other tenant were written by
the CLI's ``--tenant``, or are left over from a switch back from multi-tenant
mode. They are untouched but unreachable, and this detail keeps that from
being silent (§J "Switching modes"). It is **informational**: it never
degrades the check on its own, because an operator may keep those rows on
purpose. The framework's readiness route renders a result's ``detail``
whatever its status (``simple_module_hosting/health.py``), so a HEALTHY result
still carries it. It costs nothing on a host that has no such rows. The
tenants come from the type rows the stale check already reads, and records are
counted only for the tenants that turned up.

The check reads the database, which a ``register_health_checks`` hook cannot:
it runs before the lifespan opens one. So it reads what
:meth:`~sm_records.module.RecordsModule.on_startup` parked on the module
instance, and answers HEALTHY while that is absent — during boot there is
nothing to be stale yet, and a health check that fails because it ran early is
worse than no check at all.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from simple_module_core.health import HealthCheck, HealthCheckResult, HealthStatus
from sqlalchemy import select

from sm_records._cross_tenant import read_all
from sm_records._health_counts import (
    count_invalid_records,
    count_orphaned_locales,
    invalid_detail,
    orphaned_detail,
    outside_default,
)
from sm_records.constants import REINDEX_ALL
from sm_records.index._drift import drift_detail
from sm_records.models import RecordType
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode

if TYPE_CHECKING:
    from sm_records.module import RecordsModule

__all__ = [
    "CHECK_NAME",
    "count_invalid_records",
    "count_orphaned_locales",
    "stale_reindex_check",
]

CHECK_NAME = "records.reindex"

logger = logging.getLogger(__name__)


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


def _stale(rows, limit: int, now: datetime) -> tuple[list[tuple[str, str]], bool]:
    """``([(tenant, description)], any unique field affected)``."""
    out: list[tuple[str, str]] = []
    blocked = False
    for tenant, key, pending, fields in rows:
        late = [
            field
            for field, at in _entries(pending).items()
            if (age := _age_seconds(at, now)) is not None and age > limit
        ]
        if late:
            if _unique_keys(fields) & set(late):
                blocked = True
            names = ", ".join("whole type" if f == REINDEX_ALL else f for f in sorted(late))
            out.append((str(tenant), f"{tenant}/{key} ({names})"))
    return out, blocked


def _stale_detail(limit: int, stale: list[tuple[str, str]], blocked: bool, named: bool) -> str:
    if named:
        what = "; ".join(description for _, description in stale)
    else:
        what = f"{len(stale)} type(s) across {len({t for t, _ in stale})} tenant(s)"
    detail = (
        f"reindex pending for longer than {limit}s: {what} — run `python -m sm_records.cli reindex`"
    )
    if blocked:
        detail += (
            "; a unique field is among them, so writes to this type are refused "
            "until the rebuild completes"
        )
    return detail


def _details(limit, stale, blocked, invalid, orphaned, *, named: bool) -> list[str]:
    """The degrading details, named (single mode, the log) or counts only
    (the multi-mode response) — see the module docstring."""
    details: list[str] = []
    if stale:
        details.append(_stale_detail(limit, stale, blocked, named))
    # Reported alongside rather than instead: a stale rebuild and a drifted
    # aggregate are different faults with different fixes, and a check that
    # showed only the first would hide the second for as long as any type
    # had a marker set.
    drift = drift_detail(named=named)
    if drift is not None:
        details.append(drift)
    if invalid:
        details.append(invalid_detail(invalid, named=named))
    # Counted at startup and parked on the instance: see the module docstring
    # for why it is not recounted on a settings edit.
    if orphaned:
        details.append(orphaned_detail(orphaned, named=named))
    return details


def _log_named(module: Any, named: list[str]) -> None:
    """The multi-mode names, for the operator: logged when the wording changes,
    so a degraded host polled every few seconds does not log it every time."""
    text = "; ".join(named)
    if text and text != getattr(module, "health_logged", None):
        logger.info("records health (named, multi-tenant): %s", text)
    module.health_logged = text


def stale_reindex_check(module: RecordsModule) -> HealthCheck:
    async def check() -> HealthCheckResult:
        db_state = getattr(module, "db", None)
        if db_state is None:
            return HealthCheckResult(status=HealthStatus.HEALTHY)
        settings = getattr(module, "settings", None) or RecordsSettings()
        limit = settings.reindex_stale_after_seconds
        now = utcnow()
        async with db_state.session_factory() as session:
            stmt = select(
                RecordType.tenant_id, RecordType.key, RecordType.reindex_pending, RecordType.fields
            ).order_by(RecordType.tenant_id, RecordType.key)
            rows = (await read_all(session, stmt)).all()
            # On the same session as the rows above: one connection checked
            # out per health poll, not two.
            invalid = await count_invalid_records(session)
            multi = getattr(module, "tenancy_mode", TenancyMode.SINGLE) is TenancyMode.MULTI
            outside = None
            if not multi:
                outside = await outside_default(session, {str(row[0]) for row in rows})
        stale, blocked = _stale(rows, limit, now)
        orphaned = getattr(module, "orphaned_locales", None)
        named = _details(limit, stale, blocked, invalid, orphaned, named=True)
        details = named
        if multi:
            details = _details(limit, stale, blocked, invalid, orphaned, named=False)
            _log_named(module, named)
        # Informational, never a degradation: rows an operator keeps in another
        # tenant on purpose must not leave the check degraded for good. The
        # framework's readiness route shows ``detail`` whatever the status.
        status = HealthStatus.DEGRADED if details else HealthStatus.HEALTHY
        if outside is not None:
            details.append(outside)
        return HealthCheckResult(status=status, detail="; ".join(details) or None)

    return HealthCheck(name=CHECK_NAME, check=check)
