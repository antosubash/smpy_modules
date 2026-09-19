"""Driving the read path through the real endpoints, and labelling its plans.

Split out of ``test_read_path`` for the 300-line cap: this module owns "make
the request, time it, count its statements, explain its heaviest query", and
the test module owns which URLs are worth measuring.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles
from tests.perf._bench import (
    Results,
    capture,
    explain,
    plan_scans_records,
    plan_temp_btree,
    repeat,
)
from tests.perf.conftest import REPS

API = "/api/records/types"
HEADERS = roles(ADMIN)


async def get_ok(client, url: str):
    response = await client.get(url, headers=HEADERS)
    assert response.status_code == 200, f"{url} -> {response.status_code} {response.text[:300]}"
    return response


def plan_label(plan: list[str]) -> str:
    """One cell of the results table: which index the plan used, or the
    full-scan shape design §7.2 exists to prevent."""
    if plan_scans_records(plan):
        return "SCAN records_record"
    used = [line.split("USING")[1].strip() for line in plan if "USING" in line]
    names = sorted({item.replace("COVERING ", "").split(" (")[0] for item in used})
    label = ",".join(names) or "?"
    if plan_temp_btree(plan):
        label += " +TEMP B-TREE"
    return label[:70]


async def measure(client, label: str, url: str, n: int, engine, session):
    """Time ``url`` over ``REPS`` repetitions, then record one more call's
    statement count and the query plan of its biggest statement."""
    timing = await repeat(lambda: get_ok(client, url), reps=REPS, warmup=3)
    with capture(engine) as box:
        await get_ok(client, url)
    plan = await explain(session, *box.longest())
    Results.add(label, n, timing, statements=box.count, plan=plan_label(plan), plan_lines=plan)
    return box, plan
