"""The collections measurement, in a process that declares one — Phase 5 §6.

``declare_collection`` is a process-global side effect that has to run before
any app is built (§6.1), and it adds eight tables to ``Base.metadata`` for the
rest of the interpreter's life. A perf file that declared one at import would
therefore change every other measurement in the session — the seeded file would
gain the collection's tables, and ``referrers`` would walk two table sets in
rows that are supposed to describe a host with none.

So this is a **worker**: ``test_collections.py`` starts it, it declares what it
was told to, measures, and prints one JSON object on stdout. Same reason
``tests/test_collections_inert.py`` asserts the Phase 4 table list in a
subprocess.

Usage: ``python -m tests.perf._collection_worker <db path> <records> <collections>``
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

FIELDS = [
    {
        "key": "name",
        "type": "text",
        "label": "Name",
        "required": False,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": {},
    },
    {
        "key": "capacity",
        "type": "integer",
        "label": "Capacity",
        "required": False,
        "unique": False,
        "indexed": True,
        "default": None,
        "help": None,
        "constraints": {},
        "options": {},
    },
]


async def _fill(session, rtype, settings, count: int, create_record) -> None:
    for i in range(count):
        await create_record(
            session, rtype, data={"name": f"Row {i:06d}", "capacity": i % 500}, settings=settings
        )
        if i % 200 == 199:
            await session.commit()
    await session.commit()


async def _measure(session, engine, label: str, run, reps: int, out: list[dict[str, Any]]) -> None:
    from tests.perf._bench import capture, explain, repeat

    timing = await repeat(run, reps=reps, warmup=3)
    with capture(engine) as box:
        await run()
    plan = await explain(session, *box.longest())
    out.append(
        {
            "operation": label,
            "p50": timing.p50,
            "p95": timing.p95,
            "reps": len(timing.samples),
            "statements": box.count,
            "plan": plan,
        }
    )


async def main(path: Path, records: int, collections: int, reps: int) -> None:
    from sm_records.collections import declare_collection

    names = ["perfc", "perfd"][:collections]
    for name in names:
        declare_collection(name)

    from simple_module_db.listeners import register_listeners
    from simple_module_db.session import init_db
    from sm_records.index.query import build_query
    from sm_records.models import Base
    from sm_records.services._relations import referrers
    from sm_records.services.records import create_record
    from sm_records.services.types import create_type
    from sm_records.settings import RecordsSettings

    if path.exists():
        path.unlink()
    state = init_db(f"sqlite+aiosqlite:///{path}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = RecordsSettings()
    rows: list[dict[str, Any]] = []
    async with state.session_factory() as session:
        made = {}
        for key, collection in (("gbench", None), ("cbench", names[0] if names else None)):
            made[key] = await create_type(
                session,
                key=key,
                label=key.title(),
                settings=settings,
                fields_raw=FIELDS,
                display_field="name",
                slug_field="name",
                collection=collection,
            )
        await session.commit()

        for _key, rtype in made.items():
            where = "collection" if rtype.collection else "global"
            began = time.perf_counter()
            await _fill(session, rtype, settings, records, create_record)
            elapsed = time.perf_counter() - began
            rows.append(
                {
                    "operation": f"seed {records} records ({where})",
                    "p50": elapsed * 1000.0,
                    "p95": elapsed * 1000.0,
                    "reps": 1,
                    "statements": "batched",
                    "plan": f"{records / max(elapsed, 1e-9):.0f} rec/s",
                }
            )

            seq = {"n": 0}

            async def one(rtype=rtype, seq=seq):
                seq["n"] += 1
                await create_record(
                    session,
                    rtype,
                    data={"name": f"Bench {seq['n']:06d}", "capacity": seq["n"] % 500},
                    settings=settings,
                )
                await session.commit()

            await _measure(session, state.engine, f"create_record ({where})", one, reps, rows)

            fields = list(rtype.fields or [])

            async def page(rtype=rtype, fields=fields):
                await session.execute(build_query(rtype, fields).limit(25))

            await _measure(session, state.engine, f"list page 25 ({where})", page, reps, rows)

            from sm_records.index.query import Filter, FilterOp

            async def filtered(rtype=rtype, fields=fields):
                await session.execute(
                    build_query(rtype, fields, [Filter("capacity", FilterOp.GTE, "100")]).limit(25)
                )

            await _measure(
                session, state.engine, f"list, number gte filter ({where})", filtered, reps, rows
            )

            from sm_records.index.query import Sort

            async def sorted_(rtype=rtype, fields=fields):
                await session.execute(
                    build_query(rtype, fields, [], [Sort("name", False)]).limit(25)
                )

            await _measure(
                session, state.engine, f"list, sort by name ({where})", sorted_, reps, rows
            )

            record = (await session.execute(build_query(rtype, fields).limit(1))).scalars().first()

            async def who(record=record):
                await referrers(session, record)

            await _measure(
                session,
                state.engine,
                f"referrers ({where}, {len(names)} collection(s) declared)",
                who,
                reps,
                rows,
            )

    await state.engine.dispose()
    print(json.dumps({"collections": names, "records": records, "rows": rows}))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    asyncio.run(main(Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])))
