"""What a registered reduce spec costs a write — Phase 5 §5, the inert half.

The design's promise is that a host which registers nothing runs the Phase 4
write path unchanged, and that one which registers a spec pays **one
statement** per write in the steady state. Both halves are measured here as a
*pair in one process* against the same records: the registry is process-global
and the only honest way to price it is to turn it on and off around the same
create.

The first sight of a group costs four rather than one, and that is not a
regression to fix: the ``UPDATE`` matching no row is the only signal a group
has never been counted, and the savepoint around the insert is what keeps a
racing writer's ``IntegrityError`` from killing the transaction. A type has as
many first sights as it has groups, ever.

Everything runs on ``perf_db_copy``: a reduce row written into the shared
seeded file would be read by the next run as if a host had registered the spec.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index.reduce import (
    ReduceSpec,
    clear_reduce_providers,
    register_reduce_provider,
)
from sm_records.models import RecordStatus
from sm_records.services import records as record_service

from tests.perf._bench import Results, capture, repeat
from tests.perf.conftest import REPS, load_type, type_counts
from tests.perf.test_write_path import _company, _next

pytestmark = pytest.mark.perf

KEY = "companies_per_state"


def _spec() -> ReduceSpec:
    """Groups the companies by state and folds their headcount.

    ``company`` rather than ``order`` because the write-path measurements
    already create companies and the two tables then describe the same write.
    """
    return ReduceSpec(
        key=KEY,
        group_by=lambda record, rtype: (record.data or {}).get("state"),
        value=lambda record, rtype: Decimal((record.data or {}).get("employees") or 0),
    )


@pytest.fixture
def no_specs():
    """Whatever an earlier file registered, gone — and gone again after."""
    clear_reduce_providers()
    yield
    clear_reduce_providers()


async def _create(session, rtype, settings, state: str = "CA"):
    payload = _company(_next())
    payload["state"] = state
    record = await record_service.create_record(
        session, rtype, data=payload, settings=settings, status=RecordStatus.PUBLISHED
    )
    await session.commit()
    return record


async def test_a_write_costs_nothing_when_no_spec_is_registered(perf_db_copy, settings, no_specs):
    """The inert claim, as a number: the Phase 4 create, unchanged.

    Measured first and recorded as the control for the row below it, so the
    two are one process, one file and one type apart.
    """
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "company")
        counts = await type_counts(session)
        total = sum(counts.values())

        async def one():
            await _create(session, rtype, settings)

        timing = await repeat(one, reps=REPS, warmup=3)
        with capture(perf_db_copy.engine) as box:
            await one()
        Results.add("create_record(company), no reduce spec", total, timing, statements=box.count)
        assert box.matching("records_index_reduce") == [], (
            "a host that registered no spec touched the reduce table"
        )
        Results.note(f"reduce off: create_record(company) = {box.count} statements")


async def test_one_spec_costs_one_statement_in_the_steady_state(perf_db_copy, settings, no_specs):
    """Off, then on, against the same type in the same process.

    The delta is the whole measurement: the second number must be the first
    plus one once the group exists, and plus four the first time it is seen.
    """
    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "company")
        counts = await type_counts(session)
        total = sum(counts.values())

        with capture(perf_db_copy.engine) as off:
            await _create(session, rtype, settings)

        register_reduce_provider(_spec())

        # First sight of this group: the reduce table is empty until a spec
        # exists, so the UPDATE matches nothing and the savepoint + INSERT +
        # RELEASE follow it.
        with capture(perf_db_copy.engine) as first:
            await _create(session, rtype, settings, state="NY")
        # Steady state: the group exists and the delta is one UPDATE.
        with capture(perf_db_copy.engine) as steady:
            await _create(session, rtype, settings, state="NY")

        async def one():
            await _create(session, rtype, settings, state="NY")

        timing = await repeat(one, reps=REPS, warmup=3)
        Results.add(
            "create_record(company), 1 reduce spec (steady)",
            total,
            timing,
            statements=steady.count,
            plan=f"+{steady.count - off.count} vs off, +{first.count - off.count} first sight",
        )
    assert steady.count == off.count + 1, (
        f"a registered spec cost {steady.count - off.count} statements per write, not 1"
    )
    assert first.count == off.count + 4, (
        f"the first sight of a group cost {first.count - off.count} statements, not 4"
    )
    Results.note(
        f"reduce on: {off.count} -> {steady.count} statements per create "
        f"(+1 steady, +{first.count - off.count} on a group's first sight)"
    )


async def test_an_edit_that_does_not_move_the_group_costs_nothing(perf_db_copy, settings, no_specs):
    """A spec whose contribution is unchanged issues no statement at all.

    The common edit — a field the fold does not read — must not tell the
    database anything, or a maintained aggregate would tax every write on the
    type rather than the ones that move it.
    """
    from sm_records.models import RevisionEvent

    async with perf_db_copy.session_factory() as session:
        rtype = await load_type(session, "company")
        register_reduce_provider(
            ReduceSpec(key=KEY, group_by=lambda record, rtype: (record.data or {}).get("state"))
        )
        record = await _create(session, rtype, settings)
        payload = dict(record.data or {})
        version = record.version
        counts = await type_counts(session)

        async def edit(n: int):
            nonlocal version
            data = dict(payload)
            data["city"] = f"Palo Alto {n}"
            updated = await record_service.update_record(
                session,
                rtype,
                record,
                expected_version=version,
                data=data,
                settings=settings,
                event=RevisionEvent.UPDATE,
            )
            version = updated.version
            await session.commit()

        await edit(0)
        with capture(perf_db_copy.engine) as box:
            await edit(1)
        state = {"n": 1}

        async def one():
            state["n"] += 1
            await edit(state["n"])

        timing = await repeat(one, reps=REPS, warmup=2)
        Results.add(
            "update_record(company), 1 reduce spec, group unchanged",
            sum(counts.values()),
            timing,
            statements=box.count,
        )
    touched = [row for row in box.statements if "records_index_reduce" in row[0]]
    assert touched == [], f"an edit that did not move the group issued {len(touched)} statement(s)"
