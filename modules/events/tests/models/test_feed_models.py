"""The private feed and import tables (PR 5): keys, cascades and defaults."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, EventImport, EventImportItem, FeedToken
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def _calendar(db, slug="team") -> Calendar:
    cal = Calendar(slug=slug, name=slug.title(), owner_id="o")
    db.add(cal)
    await db.flush()
    return cal


def _token(calendar_id, digest: str = "a" * 64) -> FeedToken:
    return FeedToken(
        calendar_id=calendar_id, user_id="u", token_hash=digest, label="Phone", locale="en"
    )


@pytest.mark.unbound_tenant
async def test_feed_token_hash_unique_across_tenants(db):
    """One hash, one row in the whole install: the route finds the row before it knows a tenant."""
    with tenant_scope("a"):
        first = await _calendar(db)
        db.add(_token(first.id))
        await db.flush()
    with tenant_scope("b"):
        second = await _calendar(db)
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(_token(second.id))
                await db.flush()


async def test_import_cascade(db):
    cal = await _calendar(db)
    doomed = EventImport(calendar_id=cal.id, created_by="u", status="staged", filename="a.ics")
    kept = EventImport(calendar_id=cal.id, created_by="u", status="staged", filename="b.ics")
    db.add_all([doomed, kept, _token(cal.id)])
    await db.flush()
    for imp in (doomed, kept):
        db.add(EventImportItem(import_id=imp.id, seq=1, uid="x@y", verdict="new", title="T"))
    await db.flush()
    await db.delete(doomed)
    await db.flush()
    assert len((await db.execute(select(EventImportItem))).scalars().all()) == 1
    # A hard delete (the ORM's ``delete`` would only trash a calendar): the database cascades.
    await db.execute(
        sa_delete(Calendar.__table__).where(  # type: ignore[arg-type]
            Calendar.__table__.c.id == cal.id, Calendar.__table__.c.tenant_id == "default"
        )
    )
    db.expire_all()
    for model in (EventImport, EventImportItem, FeedToken):
        assert (await db.execute(select(model))).scalars().all() == [], model


async def test_import_item_seq_unique_per_import(db):
    cal = await _calendar(db)
    imp = EventImport(calendar_id=cal.id, created_by="u", status="staged", filename="a.ics")
    db.add(imp)
    await db.flush()
    db.add(EventImportItem(import_id=imp.id, seq=1, uid="x@y", verdict="new", title="T"))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(EventImportItem(import_id=imp.id, seq=1, uid="z@y", verdict="new", title="T"))
            await db.flush()


async def test_import_source_binary(db):
    cal = await _calendar(db)
    raw = bytes(range(256)) * 4096  # 1 MiB, every byte value
    imp = EventImport(
        calendar_id=cal.id, created_by="u", status="uploaded", filename="a.ics", source=raw
    )
    db.add(imp)
    await db.flush()
    db.expire_all()
    again = (await db.execute(select(EventImport))).scalar_one()
    assert again.source == raw
    assert (again.total, again.processed, again.created) == (0, 0, 0)
    assert again.counts == {} and again.reasons == {} and again.dropped == {}
    again.source = None
    await db.flush()


async def test_feed_token_defaults(db):
    cal = await _calendar(db)
    token = _token(cal.id)
    db.add(token)
    await db.flush()
    assert token.id is not None
    assert token.tenant_id == "default"
    assert token.created_at is not None
    assert token.last_used_at is None and token.revoked_at is None
