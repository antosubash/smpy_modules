"""Opt-in SQLite capacity measurement; never touches the host database.

Run from repo root: uv run python modules/analytics/tests/perf/benchmark.py
"""

import asyncio
import json
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sm_analytics.collection.service import collect
from sm_analytics.core.geo import GeoResolver
from sm_analytics.models import AnalyticsProperty, Base
from sm_analytics.reporting.reports import report
from sm_analytics.web.schemas import CollectIn
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

OUTPUT = Path(".verify/analytics")
DB = OUTPUT / "benchmark.db"


def seed() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        raise SystemExit(f"{DB} already exists; use its saved results or move it before rerunning")
    engine = create_engine(f"sqlite:///{DB}")
    Base.metadata.create_all(engine)
    engine.dispose()
    connection = sqlite3.connect(DB)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        "INSERT INTO analytics_property VALUES "
        "('benchmark','p','Site','public','[]',1,'[]','{}','[]')"
    )
    connection.execute("CREATE TEMP TABLE numbers (n INTEGER PRIMARY KEY)")
    connection.executemany("INSERT INTO numbers VALUES (?)", ((n,) for n in range(100000)))
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    started = time.monotonic()
    columns = list(Base.metadata.tables["analytics_event"].columns)
    values = {c.name: "''" for c in columns}
    values.update(
        tenant_id="'benchmark'",
        id="printf('%d-%d', :day,n)",
        property_id="'p'",
        session_id="printf('%d-%d', :day,n%10000)",
        event_id="printf('%d-%d', :day,n)",
        visitor="printf('%d-%d', :day,n%10000)",
        created_at=":stamp",
        kind="'pageview'",
        path="'/p/' || (n%50)",
        properties="'{}'",
        browser="'Firefox'",
        os="'Linux'",
        device="'desktop'",
        country="CASE WHEN n%2=0 THEN 'AT' ELSE 'DE' END",
        country_name="CASE WHEN n%2=0 THEN 'Austria' ELSE 'Germany' END",
    )
    sql = (
        f"INSERT INTO analytics_event ({','.join(values)}) "
        f"SELECT {','.join(values.values())} FROM numbers"
    )
    for day in range(90):
        stamp = (now - timedelta(days=day)).strftime("%Y-%m-%d %H:%M:%S.%f")
        params = {"day": day, "stamp": stamp}
        connection.execute(
            "INSERT INTO analytics_session SELECT 'benchmark',printf('%d-%d',:day,n),'p',"
            "printf('%d-%d',:day,n),:stamp,:stamp FROM numbers WHERE n<10000",
            params,
        )
        connection.execute(sql, params)
        connection.commit()
        if day % 10 == 9:
            print(f"Seeded {(day + 1) * 100000:,} events", flush=True)
    elapsed = time.monotonic() - started
    connection.execute("ANALYZE")
    connection.close()
    return {
        "backend": "SQLite",
        "events": 9000000,
        "seed_seconds": elapsed,
        "bulk_seed_events_per_second": 9000000 / elapsed,
        "bytes": DB.stat().st_size,
    }


async def measure(result: dict) -> None:
    # Periodic timer also makes this runnable in sandboxes blocking thread wakeup sockets.
    async def tick():
        while True:
            await asyncio.sleep(0.01)

    task = asyncio.create_task(tick())
    engine = create_async_engine(f"sqlite+aiosqlite:///{DB}")
    try:
        today = datetime.now(UTC).date()
        async with AsyncSession(engine) as db:
            prop = await db.get(AnalyticsProperty, "p")
            for days in (7, 90):
                start = time.monotonic()
                data = await report(
                    db, "benchmark", prop, start=today - timedelta(days=days - 1), end=today
                )
                assert data["totals"]["pageviews"] == days * 100000
                result[f"report_{days}_days_seconds"] = time.monotonic() - start
            prop.route_patterns = ["/p/:slug"]
            prop.origins = ["https://benchmark.invalid"]
            await db.commit()
            started = time.monotonic()
            for _ in range(1000):
                assert await collect(
                    db,
                    CollectIn(property_id="p", event_id=uuid4(), kind="pageview", path="/p/ingest"),
                    tenant="benchmark",
                    ip="127.0.0.1",
                    ua="Firefox/123",
                    secret="benchmark-key",
                    geo=GeoResolver(),
                    now=datetime.now(UTC),
                    source_origin="https://benchmark.invalid",
                )
                await db.commit()
            result["collector_events_per_second"] = 1000 / (time.monotonic() - started)
        result["note"] = (
            "Bulk SQL seed speed is not collector throughput; this does not certify capacity."
        )
    finally:
        await engine.dispose()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    (OUTPUT / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(measure(seed()))
