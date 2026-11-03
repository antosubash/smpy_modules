"""The refresh upsert: one atomic statement per chunk, newest time wins, exact counts.

Runs on both backends (``SM_TEST_DATABASE_URL`` selects Postgres).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sm_newsletter.core.suppression import clear_for_confirmation, suppress, suppress_many
from sm_newsletter.models import Suppression
from sqlalchemy import delete, event, select

from tests.pg_support import USING_POSTGRES

# Microsecond 0 on purpose: SQLite stores a fixed-width UTC string, so
# ``max()`` must order "…:00.000000" below "…:00.500000".
T0 = datetime(2026, 11, 1, 9, 0, 0, tzinfo=UTC)
T0_HALF = T0 + timedelta(microseconds=500_000)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)
ADA = "ada@example.org"
BOUNCE = {"tenant_id": "default", "reason": "hard_bounce"}


async def _rows(db) -> list[Suppression]:
    db.expire_all()
    return list((await db.execute(select(Suppression).order_by(Suppression.id))).scalars())


async def test_a_row_deleted_before_the_refresh_is_recreated(db):
    """The lost-update race: a confirmation deletes the row, then the bounce lands."""
    assert await suppress(db, email=ADA, source="send", now=T0, **BOUNCE) is True
    await db.execute(delete(Suppression.__table__))
    assert await suppress(db, email=ADA, source="admin", now=T2, **BOUNCE) is True
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T2, "admin")


async def test_an_older_time_changes_neither_time_nor_source(db):
    await suppress(db, email=ADA, source="send", now=T2, **BOUNCE)
    assert await suppress(db, email=ADA, source="admin", now=T0, **BOUNCE) is False
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T2, "send")


async def test_the_same_time_keeps_the_source(db):
    await suppress(db, email=ADA, source="send", now=T1, **BOUNCE)
    await suppress(db, email=ADA, source="admin", now=T1, **BOUNCE)
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T1, "send")


async def test_a_newer_time_wins_and_takes_the_source(db):
    await suppress(db, email=ADA, source="send", now=T0, **BOUNCE)
    await suppress(db, email=ADA, source="admin", now=T0_HALF, **BOUNCE)
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T0_HALF, "admin")


async def test_comparison_is_by_instant_not_by_written_offset(db):
    # 10:30+02:00 is 08:30 UTC: earlier than T0 although its wall clock is later.
    earlier = datetime(2026, 11, 1, 10, 30, tzinfo=timezone(timedelta(hours=2)))
    await suppress(db, email=ADA, source="send", now=T0, **BOUNCE)
    await suppress(db, email=ADA, source="admin", now=earlier, **BOUNCE)
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T0, "send")


async def test_mixed_batch_past_500_counts_only_inserts(db):
    emails = [f"user{i}@example.org" for i in range(1300)]
    assert await suppress_many(db, emails=emails[:700:2], source="send", now=T0, **BOUNCE) == 350
    assert await suppress_many(db, emails=emails, source="admin", now=T2, **BOUNCE) == 950
    rows = await _rows(db)
    assert len(rows) == 1300
    assert {(r.created_at, r.source) for r in rows} == {(T2, "admin")}
    assert await suppress_many(db, emails=emails, source="send", now=T1, **BOUNCE) == 0
    assert {(r.created_at, r.source) for r in await _rows(db)} == {(T2, "admin")}


async def test_refresh_false_counts_and_leaves_rows_untouched(db):
    emails = [f"user{i}@example.org" for i in range(620)]
    await suppress_many(db, emails=emails[:300], source="send", now=T0, **BOUNCE)
    got = await suppress_many(
        db, emails=emails, source="reconcile", now=T2, refresh=False, **BOUNCE
    )
    assert got == 320
    by_source = {(r.created_at, r.source) for r in await _rows(db)}
    assert by_source == {(T0, "send"), (T2, "reconcile")}


def _watch(db, seen: list[str]):
    """A listener that records every SQL statement, whitespace-folded, upper-cased."""

    def _record(conn, cursor, statement, params, context, executemany):
        seen.append(" ".join(statement.split()).upper())

    event.listen(db.get_bind(), "before_cursor_execute", _record)
    return _record


async def test_refresh_is_one_upsert_per_chunk_and_never_a_bare_update(db):
    emails = [f"user{i}@example.org" for i in range(1200)]
    await suppress_many(db, emails=emails[:600], source="send", now=T0, **BOUNCE)
    seen: list[str] = []
    listener = _watch(db, seen)
    try:
        assert await suppress_many(db, emails=emails, source="admin", now=T2, **BOUNCE) == 600
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)
    writes = [s for s in seen if "NEWSLETTER_SUPPRESSION" in s and not s.startswith("SELECT")]
    assert not [s for s in writes if s.startswith("UPDATE")]
    upserts = [s for s in writes if "ON CONFLICT" in s and "DO UPDATE" in s]
    assert len(upserts) == 3  # 1200 rows in chunks of 500
    if USING_POSTGRES:
        # Count and refresh come from the same statement: nothing to interleave.
        assert writes == upserts


async def test_a_refreshed_row_is_newer_than_an_earlier_confirmation(db):
    unsub = {"tenant_id": "default", "reason": "unsubscribed", "list_type_key": "news"}
    await suppress(db, email=ADA, source="records_event", now=T0, **unsub)
    await suppress(db, email=ADA, source="records_event", now=T2, **unsub)
    cleared = await clear_for_confirmation(
        db, tenant_id="default", email=ADA, list_type_key="news", confirmed_at=T1
    )
    assert cleared == 0
    [row] = await _rows(db)
    assert (row.reason, row.created_at) == ("unsubscribed", T2)
