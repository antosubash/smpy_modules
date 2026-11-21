"""Seed a subscription's cached items for the browser suite, through the module's own store.

    uv run python tests/e2e/support/seed_external.py <database url> <subscription id> <feed.ics>

The browser suite never fetches a live feed (the fetcher refuses loopback on purpose, and a test
host must not be given a way around that), so a spec that needs external items on a calendar
calls this once: the rows are written by ``store_feed`` itself, shaped exactly as a real refresh
would shape them. Test support only: it lives here, outside every package, and nothing imports it.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from simple_module_db import init_db
from simple_module_db.listeners import attach_session_listeners
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.subscriptions.store import store_feed
from sm_events.models import Calendar, Subscription
from sqlalchemy import select

TENANT = "default"


async def main(url: str, subscription_id: str, feed: Path) -> None:
    state = init_db(url)
    attach_session_listeners(
        state.sync_session_class
    )  # stamps the tenant, as the app's sessions do
    try:
        with tenant_scope(TENANT):
            async with state.session_factory() as db:
                sub = (
                    await db.execute(
                        select(Subscription).where(Subscription.id == uuid.UUID(subscription_id))
                    )
                ).scalar_one()
                calendar = (
                    await db.execute(select(Calendar).where(Calendar.id == sub.calendar_id))
                ).scalar_one()
                counts = await store_feed(
                    db, sub, calendar_tz=calendar.default_timezone, body=feed.read_bytes()
                )
                # leave it as a good first refresh would, eligible for an immediate "refresh now"
                sub.status, sub.error_code, sub.last_fetched_at = "ok", None, None
                await db.commit()
        print(f"stored {counts.stored}, skipped {counts.skipped}")
    finally:
        await state.engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], Path(sys.argv[3])))
