"""Health checks the module contributes. Design doc §8.9.

Filled in by the Phase 3 services task; the stub keeps the entry point
importable so the host boots between commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simple_module_core.health import HealthCheck, HealthCheckResult, HealthStatus

if TYPE_CHECKING:
    from sm_records.module import RecordsModule


def stale_reindex_check(module: RecordsModule) -> HealthCheck:
    async def check() -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)

    return HealthCheck(name="records.reindex", check=check)
