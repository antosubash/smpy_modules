"""The suppression store: insert-or-refresh, tenant-wide lookups, cutoff clears."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sm_newsletter.core.suppression import (
    clear_for_confirmation,
    email_hash,
    suppress,
    suppress_many,
    suppressed,
)
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression
from sqlalchemy import select

T0 = datetime(2026, 11, 1, 9, 0, 0, 123456, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)
ADA = "ada@example.org"


async def _rows(db) -> list[Suppression]:
    return list((await db.execute(select(Suppression).order_by(Suppression.id))).scalars())


async def test_suppress_is_idempotent(db):
    kw = {"tenant_id": "default", "email": ADA, "reason": "hard_bounce", "source": "send"}
    assert await suppress(db, **kw) is True
    assert await suppress(db, **kw) is False
    rows = await _rows(db)
    assert len(rows) == 1
    assert (rows[0].tenant_id, rows[0].email_hash) == ("default", email_hash(ADA))


async def test_suppress_is_spelling_insensitive(db):
    await suppress(
        db, tenant_id="default", email="ADA@example.org", reason="complaint", source="send"
    )
    got = await suppressed(db, tenant_id="default", emails=[" ada@example.org", "bob@example.org"])
    assert got == {ADA}


@pytest.mark.parametrize(
    ("reason", "list_key"),
    [
        ("unsubscribed", ""),
        ("complaint", "news"),
        ("hard_bounce", "news"),
        ("nonsense", ""),
        ("unsubscribed", "x" * 65),
    ],
)
async def test_reason_and_list_must_agree(db, reason, list_key):
    with pytest.raises(ValueError):
        await suppress(
            db, tenant_id="default", email=ADA, reason=reason, source="send", list_type_key=list_key
        )
    assert await _rows(db) == []


async def test_unknown_source_and_tenant_refused(db):
    with pytest.raises(ValueError):
        await suppress(db, tenant_id="default", email=ADA, reason="complaint", source="nope")
    with pytest.raises(ValueError):
        await suppressed(db, tenant_id="bad tenant!", emails=[ADA])
    with pytest.raises(ValueError):
        await suppress(db, tenant_id="default", email="", reason="complaint", source="send")


async def test_list_and_address_wide_rows_both_suppress(db):
    await suppress(
        db,
        tenant_id="default",
        email=ADA,
        reason="unsubscribed",
        source="records_event",
        list_type_key="news",
    )
    await suppress(
        db, tenant_id="default", email="bob@example.org", reason="hard_bounce", source="send"
    )
    got = await suppressed(
        db, tenant_id="default", emails=[ADA, "bob@example.org", "cy@example.org"]
    )
    assert got == {ADA, "bob@example.org"}
    assert await suppressed(db, tenant_id="default", emails=[]) == set()


async def test_suppress_many_dedupes_and_counts_inserts(db):
    emails = [ADA, " ADA@example.org", "bob@example.org"]
    kw = {"tenant_id": "default", "reason": "imported_cleaned", "source": "import"}
    assert await suppress_many(db, emails=emails, **kw) == 2
    assert await suppress_many(db, emails=[*emails, "cy@example.org"], **kw) == 1
    assert len(await _rows(db)) == 3


async def _seed_all(db, *, now: datetime) -> None:
    for reason, list_key in [
        ("unsubscribed", "news"),
        ("unsubscribed", "other"),
        ("hard_bounce", ""),
        ("imported_cleaned", ""),
        ("complaint", ""),
    ]:
        await suppress(
            db,
            tenant_id="default",
            email=ADA,
            reason=reason,
            source="admin",
            list_type_key=list_key,
            now=now,
        )


async def test_clear_keeps_complaint_and_other_lists(db):
    await _seed_all(db, now=T0)
    deleted = await clear_for_confirmation(
        db, tenant_id="default", email=" Ada@Example.org", list_type_key="news", confirmed_at=T1
    )
    assert deleted == 3
    left = {(r.reason, r.list_type_key) for r in await _rows(db)}
    assert left == {("unsubscribed", "other"), ("complaint", "")}


async def test_clear_respects_the_cutoff(db):
    # Confirmed at T1, then a bounce at T2; the delayed confirm handler runs last.
    await suppress(db, tenant_id="default", email=ADA, reason="hard_bounce", source="send", now=T2)
    await suppress(
        db,
        tenant_id="default",
        email=ADA,
        reason="unsubscribed",
        source="records_event",
        list_type_key="news",
        now=T0,
    )
    deleted = await clear_for_confirmation(
        db, tenant_id="default", email=ADA, list_type_key="news", confirmed_at=T1
    )
    assert deleted == 1
    assert [(r.reason, r.created_at) for r in await _rows(db)] == [("hard_bounce", T2)]


async def test_clear_cutoff_is_inclusive_and_offset_independent(db):
    await suppress(db, tenant_id="default", email=ADA, reason="hard_bounce", source="send", now=T1)
    # The same instant, written in another offset: still "not after" the cutoff.
    cutoff = T1.astimezone(timezone(timedelta(hours=2)))
    assert (
        await clear_for_confirmation(
            db, tenant_id="default", email=ADA, list_type_key="news", confirmed_at=cutoff
        )
        == 1
    )


async def test_clear_needs_an_aware_cutoff(db):
    with pytest.raises(ValueError):
        await clear_for_confirmation(
            db,
            tenant_id="default",
            email=ADA,
            list_type_key="news",
            confirmed_at=datetime(2026, 11, 1, 9, 0),  # naive: the point of the test
        )


async def test_repeat_suppress_refreshes_created_at(db):
    kw = {"tenant_id": "default", "email": ADA, "reason": "hard_bounce"}
    assert await suppress(db, source="send", now=T0, **kw) is True
    assert await suppress(db, source="admin", now=T2, **kw) is False
    db.expire_all()
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T2, "admin")
    assert (
        await clear_for_confirmation(
            db, tenant_id="default", email=ADA, list_type_key="news", confirmed_at=T1
        )
        == 0
    )
    assert len(await _rows(db)) == 1


async def test_refresh_never_moves_a_row_back(db):
    kw = {"tenant_id": "default", "email": ADA, "reason": "hard_bounce", "source": "send"}
    await suppress(db, now=T2, **kw)
    await suppress(db, now=T0, **kw)
    db.expire_all()
    [row] = await _rows(db)
    assert row.created_at == T2


async def test_refresh_false_keeps_created_at(db):
    kw = {"tenant_id": "default", "reason": "unsubscribed", "list_type_key": "news"}
    assert await suppress_many(db, emails=[ADA], source="records_event", now=T0, **kw) == 1
    assert (
        await suppress_many(db, emails=[ADA], source="reconcile", now=T2, refresh=False, **kw) == 0
    )
    db.expire_all()
    [row] = await _rows(db)
    assert (row.created_at, row.source) == (T0, "records_event")


async def test_suppress_many_refreshes_existing_rows(db):
    kw = {"tenant_id": "default", "reason": "complaint", "source": "send"}
    await suppress_many(db, emails=[ADA], now=T0, **kw)
    assert await suppress_many(db, emails=[ADA, "bob@example.org"], now=T2, **kw) == 1
    db.expire_all()
    assert {r.created_at for r in await _rows(db)} == {T2}


@pytest.mark.unbound_tenant
async def test_tenant_isolation(db_state):
    async with db_state.session_factory() as session:
        with tenant_scope("a"):
            await suppress(session, tenant_id="a", email=ADA, reason="hard_bounce", source="send")
            await session.commit()
    async with db_state.session_factory() as session:
        with tenant_scope("b"):
            assert await suppressed(session, tenant_id="b", emails=[ADA]) == set()
            assert (
                await clear_for_confirmation(
                    session, tenant_id="b", email=ADA, list_type_key="news", confirmed_at=T2
                )
                == 0
            )
            await session.commit()
    async with db_state.session_factory() as session:
        with tenant_scope("a"):
            assert await suppressed(session, tenant_id="a", emails=[ADA]) == {ADA}


@pytest.mark.unbound_tenant
async def test_functions_bind_their_own_tenant(db_state):
    """Called unbound, each function binds ``tenant_id`` itself."""
    async with db_state.session_factory() as session:
        assert await suppress(session, tenant_id="a", email=ADA, reason="complaint", source="send")
        assert await suppressed(session, tenant_id="a", emails=[ADA]) == {ADA}
        assert await suppressed(session, tenant_id="b", emails=[ADA]) == set()
