"""External subscriptions (PR 10): the two tables, their keys, cascades and tenant guard."""

from __future__ import annotations

import pytest
from sm_events.core.clock import utcnow
from sm_events.models import Base, Calendar, ExternalItem, Subscription
from sqlalchemy import Index, UniqueConstraint, delete, select
from sqlalchemy.exc import IntegrityError

NOW = utcnow()


async def _subscription(db, slug="team", url_enc="enc:v2:x") -> Subscription:
    cal = Calendar(slug=slug, name=slug.title(), owner_id="o")
    db.add(cal)
    await db.flush()
    sub = Subscription(
        calendar_id=cal.id,
        created_by="o",
        url_enc=url_enc,
        url_display="https://cal.example/…",
        label="Work",
        next_fetch_at=NOW,
    )
    db.add(sub)
    await db.flush()
    return sub


def _item(sub: Subscription, uid="a@x", **fields) -> ExternalItem:
    base = {
        "subscription_id": sub.id,
        "uid": uid,
        "all_day": False,
        "starts_at": NOW,
        "ends_at": NOW,
        "timezone": "UTC",
        "span_start": NOW,
        "title": "Meeting",
        "content_hash": "0" * 64,
        "seen_generation": 1,
    }
    return ExternalItem(**{**base, **fields})


def _table(name: str):
    return Base.metadata.tables[name]


def test_tables_and_indexes():
    sub, item = _table("events_subscription"), _table("events_external_item")
    uniques = {c.name for c in item.constraints if isinstance(c, UniqueConstraint)}
    assert "uq_events_external_item_uid" in uniques
    unique = next(c for c in item.constraints if c.name == "uq_events_external_item_uid")
    assert [c.name for c in unique.columns] == ["tenant_id", "subscription_id", "uid"]
    sub_indexes = {i.name: [c.name for c in i.columns] for i in sub.indexes if isinstance(i, Index)}
    assert sub_indexes["ix_events_subscription_due"] == ["status", "next_fetch_at"]
    assert sub_indexes["ix_events_subscription_calendar"] == ["tenant_id", "calendar_id"]
    item_indexes = {i.name: [c.name for c in i.columns] for i in item.indexes}
    assert item_indexes["ix_events_external_item_window"] == [
        "tenant_id",
        "subscription_id",
        "span_start",
    ]
    for table, column, target in (
        (sub, "calendar_id", "events_calendar.id"),
        (item, "subscription_id", "events_subscription.id"),
    ):
        (fk,) = table.c[column].foreign_keys
        assert fk.target_fullname == target
        assert fk.ondelete == "CASCADE"


def test_the_url_column_is_text_so_ciphertext_always_fits():
    assert _table("events_subscription").c.url_enc.type.__class__.__name__ == "Text"


async def test_item_uid_unique_per_subscription(db):
    sub = await _subscription(db)
    db.add(_item(sub))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_item(sub))
            await db.flush()
    db.add(_item(sub, uid="b@x"))
    other = await _subscription(db, slug="other")
    db.add(_item(other))  # the same uid under another subscription is another row
    await db.flush()


async def test_defaults(db):
    sub = await _subscription(db)
    assert sub.status == "pending"
    assert (sub.consecutive_failures, sub.generation, sub.item_count) == (0, 0, 0)
    assert sub.public is False
    assert sub.is_deleted is False
    assert sub.lease_owner is None
    assert sub.last_counts == {}
    item = _item(sub)
    assert (item.cancelled, item.private_class) == (False, False)
    assert item.overrides == []


async def test_deleting_a_calendar_cascades_to_subscriptions_and_items(db):
    sub = await _subscription(db)
    db.add(_item(sub))
    await db.flush()
    # SQLite enforces the cascade only with foreign keys on, which the harness turns on.
    await db.execute(delete(Calendar))
    await db.flush()
    db.expire_all()
    assert (await db.execute(select(Subscription))).scalars().all() == []
    assert (await db.execute(select(ExternalItem))).scalars().all() == []


@pytest.mark.unbound_tenant
async def test_tenant_guarded(db_state):
    from sm_events.core.tenancy import TenantUnbound, all_tenants, install_guard

    install_guard(db_state.sync_session_class)
    async with db_state.session_factory() as session:
        for model in (Subscription, ExternalItem):
            with pytest.raises(TenantUnbound):
                await session.execute(select(model))
            await session.execute(all_tenants(select(model)))
