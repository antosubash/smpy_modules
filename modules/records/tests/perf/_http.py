"""Driving the read path through the real endpoints, and labelling its plans.

Split out of ``test_read_path`` for the 300-line cap: this module owns "make
the request, time it, count its statements, explain its heaviest query", and
the test module owns which URLs are worth measuring.
"""

from __future__ import annotations

import re

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


#: Postgres's spellings of "this node read an index". ``Index Scan using X on
#: t`` and ``Index Only Scan using X on t`` name the index after ``using``;
#: ``Bitmap Index Scan on X`` names it after ``on``, because the *heap* access
#: is a separate node. Case-sensitive on purpose — SQLite shouts ``USING`` and
#: is handled by the branch above, and keeping the two patterns disjoint is
#: what lets one function serve both without either changing the other's output.
_PG_INDEX = re.compile(r"(?:Index(?: Only)? Scan using|Bitmap Index Scan on)\s+(\S+)")


def plan_label(plan: list[str]) -> str:
    """One cell of the results table: which index the plan used, or the
    full-scan shape design §7.2 exists to prevent.

    **Both dialects, since the Postgres study of 2026-09-21.** The SQLite
    branch splits on ``USING`` because that is how ``EXPLAIN QUERY PLAN``
    writes it (``SEARCH t USING INDEX ix_… (type_id=?)``). Postgres writes
    ``Index Scan using ix_… on t``, in lower case, which that split does not
    see — so every row of the first Postgres run of this suite reported its
    plan as ``?`` and the column, which is most of why the table exists, said
    nothing. The SQLite label is deliberately left byte-for-byte as it was,
    ``INDEX `` prefix and all, so the numbers already recorded in
    ``docs/performance.md`` stay comparable with new ones.
    """
    if plan_scans_records(plan):
        return "SCAN records_record"
    used = [line.split("USING")[1].strip() for line in plan if "USING" in line]
    names = {item.replace("COVERING ", "").split(" (")[0] for item in used}
    names |= {match.group(1) for line in plan for match in _PG_INDEX.finditer(line)}
    label = ",".join(sorted(names)) or "?"
    if plan_temp_btree(plan):
        label += " +TEMP B-TREE"
    return label[:70]


async def measure(client, label: str, url: str, n: int, engine, session, *, plan_of: str = ""):
    """Time ``url`` over ``REPS`` repetitions, then record one more call's
    statement count and the query plan of its biggest statement.

    ``plan_of`` names a substring of the statement whose plan is wanted
    instead. The default — the biggest statement — is right for a list page,
    where the filtered ``SELECT`` is also the longest text. It is wrong for an
    aggregate: the ``GROUP BY`` is short and the type load, with its column
    list, is long, so the plan cell would describe the wrong query and the
    "does not scan ``records_record``" assertion would pass vacuously.
    """
    timing = await repeat(lambda: get_ok(client, url), reps=REPS, warmup=3)
    with capture(engine) as box:
        await get_ok(client, url)
    wanted = box.matching(plan_of) if plan_of else []
    plan = await explain(session, *(wanted[0] if wanted else box.longest()))
    Results.add(label, n, timing, statements=box.count, plan=plan_label(plan), plan_lines=plan)
    return box, plan
