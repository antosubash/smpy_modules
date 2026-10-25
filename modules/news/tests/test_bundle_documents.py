"""Small helpers of the news bundle section's documents (#80)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from news.integrations.bundle.documents import IN_BATCH, batches, comparable


def test_one_instant_spells_one_way_whatever_its_offset():
    berlin = datetime(2026, 5, 1, 11, 30, tzinfo=timezone(timedelta(hours=2)))
    utc = datetime(2026, 5, 1, 9, 30, tzinfo=UTC)
    a = comparable({"published_at": berlin.isoformat()})
    b = comparable({"published_at": utc.isoformat()})
    assert a == b == {"published_at": "2026-05-01T09:30:00+00:00"}


def test_ids_are_sliced_for_an_in_clause():
    ids = list(range(IN_BATCH * 2 + 1))
    chunks = list(batches(ids))
    assert [len(c) for c in chunks] == [IN_BATCH, IN_BATCH, 1]
    assert [i for c in chunks for i in c] == ids
    assert list(batches([])) == []
