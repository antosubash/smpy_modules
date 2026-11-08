"""``import_subscribers`` against an address records already holds
(newsletter PR 7, task 2; R3's records column, D5).

A pending signup is never confirmed, nobody who left is resubscribed, the
trash is never written, and a merge into a confirmed subscriber validates.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_records.records.services import records as record_service

from tests.support.newsletter_import import (
    ADA,
    NOW,
    T,
    make_list,
    outcomes,
    row,
    run,
    seed,
    stored,
)


async def test_existing_confirmed_appends_tags_and_fills_empty_fields(site):
    await make_list(site)
    await seed(site, ADA, data={"last_name": "Lovelace", "tags": ["b"]})
    new = row(ADA, fields={"first_name": "Ada", "last_name": "Other"}, tags=["a", "b"])
    assert outcomes(await run(site, [new])) == {ADA: "updated"}
    record = await stored(site, ADA)
    assert record.data["tags"] == ["b", "a"]
    assert (record.data["first_name"], record.data["last_name"]) == ("Ada", "Lovelace")
    assert outcomes(await run(site, [new])) == {ADA: "unchanged"}
    assert (await stored(site, ADA)).version == record.version


@pytest.mark.parametrize(
    ("fields", "tags", "refused"),
    [
        ({"team": "nope"}, [], "team"),
        ({"first_name": "x" * 101}, [], "first_name"),
        ({}, ["zzz"], "tags"),
    ],
)
async def test_existing_merge_validates(site, fields, tags, refused):
    await make_list(site)
    await seed(site, ADA, data={"first_name": "", "tags": ["b"]})
    [result] = await run(site, [row(ADA, fields={**fields, "last_name": "L"}, tags=tags)])
    assert result.outcome == "updated" and result.dropped == [refused]
    data = (await stored(site, ADA)).data
    assert data.get("team") is None
    assert data.get("first_name") in ("", None)
    assert data["tags"] == ["b"] and data["last_name"] == "L"


async def test_never_resubscribes_unsubscribed(site):
    await make_list(site)
    await seed(site, ADA, "unsubscribed")
    before = await stored(site, ADA)
    rows = [row(ADA, fields={"first_name": "Ada"}, tags=["a"])]
    assert outcomes(await run(site, rows)) == {ADA: "kept_unsubscribed"}
    after = await stored(site, ADA)
    assert (after.version, after.data) == (before.version, before.data)


async def test_pending_is_never_confirmed(site):
    await make_list(site)
    await seed(site, ADA, "pending")
    before = await stored(site, ADA)
    for status in ("confirmed", "unsubscribed"):
        result = await run(site, [row(ADA, status, unsubscribed_at=NOW, tags=["a"])])
        assert outcomes(result) == {ADA: "kept_pending"}
    after = await stored(site, ADA)
    assert after.data["sm_status"] == "pending"
    assert after.data["sm_nonce"] == before.data["sm_nonce"]
    assert after.version == before.version


async def test_unsubscribed_row_unsubscribes_confirmed_before_cutoff(site):
    await make_list(site)
    await seed(site, ADA, data={"first_name": "Ada"}, confirmed_at=T)
    rows = [row(ADA, "unsubscribed", unsubscribed_at=T + timedelta(hours=1))]
    assert outcomes(await run(site, rows)) == {ADA: "unsubscribed"}
    data = (await stored(site, ADA)).data
    assert data["sm_status"] == "unsubscribed" and data.get("first_name") is None


async def test_unsubscribed_row_keeps_reconfirmed_after_cutoff(site):
    await make_list(site)
    await seed(site, ADA, confirmed_at=T)
    rows = [row(ADA, "unsubscribed", unsubscribed_at=T - timedelta(hours=1))]
    assert outcomes(await run(site, rows)) == {ADA: "kept_confirmed"}
    assert (await stored(site, ADA)).data["sm_status"] == "confirmed"


async def test_trashed_is_never_written(site):
    await make_list(site)
    await seed(site, ADA, trashed=True)
    await seed(site, "bob@example.org", "unsubscribed", trashed=True)
    before = [await stored(site, e) for e in (ADA, "bob@example.org")]
    rows = [row(ADA, tags=["a"]), row("bob@example.org", "unsubscribed")]
    assert set(outcomes(await run(site, rows)).values()) == {"trashed"}
    after = [await stored(site, e) for e in (ADA, "bob@example.org")]
    assert [(r.version, r.is_deleted) for r in after] == [(r.version, True) for r in before]


async def test_existing_record_is_decided_under_the_row_lock(site, monkeypatch):
    """Both paths into a confirmed record take PR 6's ``lock_record`` before
    they write (the merge's ``update_record`` comes after it)."""
    from sm_records.public_submissions import campaign_import_rows

    await make_list(site)
    await seed(site, ADA)
    await seed(site, "bob@example.org", confirmed_at=T)
    calls: list[str] = []
    lock, update = campaign_import_rows.lock_record, record_service.update_record

    async def locking(db, rtype, record):
        calls.append(f"lock {record.data['sm_email']}")
        return await lock(db, rtype, record)

    async def updating(db, rtype, record, **kw):
        calls.append(f"update {record.data['sm_email']}")
        return await update(db, rtype, record, **kw)

    monkeypatch.setattr(campaign_import_rows, "lock_record", locking)
    monkeypatch.setattr(campaign_import_rows.record_service, "update_record", updating)
    rows = [
        row(ADA, tags=["a"]),
        row("bob@example.org", "unsubscribed", unsubscribed_at=T + timedelta(1)),
    ]
    assert [r.outcome for r in await run(site, rows)] == ["updated", "unsubscribed"]
    assert calls[:2] == [f"lock {ADA}", f"update {ADA}"]
    assert calls[2] == "lock bob@example.org"
