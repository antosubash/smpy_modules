#!/usr/bin/env python
"""Seed usage against the demo host's meters, through billing's service API.

    python scripts/seed_usage.py            # the single-tenant host's "default"
    python scripts/seed_usage.py <tenant>   # any tenant id

Three ``demo.exports`` consumes and three ``demo.jobs`` holds (long-lived, so
the sweeper leaves them alone), each under a fixed idempotency key: running it
again counts nothing twice. ``tests/e2e/start-test-server.sh`` runs it so the
admin Usage tab has a ledger to show and holds to release.

It goes through ``UsageService`` rather than SQL, so the rows are exactly
what a consumer's calls would write. The app is constructed, not started (as
``set_setting.py`` does), and the service is built on its session factory.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from headless_settings import headless_settings
from simple_module_db.tenancy import DEFAULT_TENANT_ID
from simple_module_hosting.app_builder import create_app

HOST_DIR = Path(__file__).resolve().parents[1] / "host"
COUNTER, GAUGE = "demo.exports", "demo.jobs"
SEEDED = 3
SOURCE = "seed"


async def _seed(tenant_id: str) -> None:
    sys.path.insert(0, str(HOST_DIR))
    import demo_meters
    from sm_billing.metering.service import UsageService
    from sm_billing.metering.validate import TTL_MAX
    from sm_billing.plans import seed_default_plan

    app = create_app(headless_settings())
    demo_meters.register(app)
    factory = app.state.sm.db.session_factory
    await seed_default_plan(factory)
    usage = UsageService(factory, meters=app.state.billing_meters)
    for i in range(SEEDED):
        await usage.consume(tenant_id, COUNTER, 1, f"seed:{COUNTER}:{i}", source=SOURCE)
        await usage.reserve(tenant_id, GAUGE, 1, f"seed:{GAUGE}:{i}", source=SOURCE, ttl=TTL_MAX)
    print(f"seeded {SEEDED} x {COUNTER} and {SEEDED} x {GAUGE} for tenant {tenant_id}")
    await app.state.sm.db.engine.dispose()


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: seed_usage.py [<tenant_id>]", file=sys.stderr)
        return 2
    asyncio.run(_seed(argv[0] if argv else DEFAULT_TENANT_ID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
