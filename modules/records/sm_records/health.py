"""Health checks the module contributes. Design doc §8.9.

A reindex orphaned by a worker restart is *recoverable* — the CLI finishes it —
but recoverable is not visible. A field that refuses filters with a 409 forever
because nothing ever ran the rebuild is noticed by whoever next tries that
filter, which turns a deploy detail into a support ticket. This degrades
``/health/ready`` instead, naming the type and the fields.

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
from sqlalchemy import select

from sm_records.constants import REINDEX_ALL
from sm_records.models import RecordType
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


def _stale(rows, limit: int, now: datetime) -> list[str]:
    out: list[str] = []
    for key, pending in rows:
        late = [
            field
            for field, at in _entries(pending).items()
            if (age := _age_seconds(at, now)) is not None and age > limit
        ]
        if late:
            names = ", ".join("whole type" if f == REINDEX_ALL else f for f in sorted(late))
            out.append(f"{key} ({names})")
    return out


def stale_reindex_check(module: RecordsModule) -> HealthCheck:
    async def check() -> HealthCheckResult:
        db_state = getattr(module, "db", None)
        if db_state is None:
            return HealthCheckResult(status=HealthStatus.HEALTHY)
        settings = getattr(module, "settings", None) or RecordsSettings()
        limit = settings.reindex_stale_after_seconds
        now = utcnow()
        async with db_state.session_factory() as session:
            rows = (await session.execute(select(RecordType.key, RecordType.reindex_pending))).all()
        stale = _stale(rows, limit, now)
        if not stale:
            return HealthCheckResult(status=HealthStatus.HEALTHY)
        return HealthCheckResult(
            status=HealthStatus.DEGRADED,
            detail=(
                f"reindex pending for longer than {limit}s: {'; '.join(stale)} — "
                "run `python -m sm_records.cli reindex`"
            ),
        )

    return HealthCheck(name=CHECK_NAME, check=check)
