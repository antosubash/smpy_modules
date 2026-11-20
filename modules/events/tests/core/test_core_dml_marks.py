"""Core DML finished with ``finalize_session`` must not depend on the session class.

``finalize_session`` commits only a session flagged as written. The framework's session class
flags DML executed through it; a plain ``async_sessionmaker`` has no such listener, so a Core
``delete``/``update`` on a ``__table__`` was silently rolled back. Every such site marks the
session itself (``mark_written``); these run them on a plain factory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sm_events.feeds.tokens import cleanup as token_cleanup
from sm_events.models import Calendar, EventFollow, FeedToken
from sm_events.reminders import cleanup as reminder_cleanup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 1, 9, tzinfo=UTC)


def _plain(state):
    factory = async_sessionmaker(state.engine, class_=AsyncSession, expire_on_commit=False)
    assert "has_writes" not in factory().sync_session.info
    return factory


async def _count(state, model) -> int:
    async with state.session_factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_feed_token_cleanup_commits_on_a_plain_session(db, db_state):
    uid = uuid.uuid4()
    cal = Calendar(slug="c", name="C", owner_id="o")
    db.add(cal)
    await db.flush()
    db.add(
        FeedToken(calendar_id=cal.id, user_id=str(uid), token_hash="a" * 64, label="L", locale="en")
    )
    await db.commit()
    assert await token_cleanup.delete_user_tokens(_plain(db_state), uid) == 1
    assert await _count(db_state, FeedToken) == 0


async def test_follow_cleanup_commits_on_a_plain_session(db, db_state):
    from tests.reminders.support import follow_row, published, seed_event  # noqa: F401

    uid = uuid.uuid4()
    cal = Calendar(slug="c", name="C", owner_id="o")
    db.add(cal)
    await db.flush()
    event = await published(db, cal)
    db.add(follow_row(event, user=str(uid)))
    await db.commit()
    await reminder_cleanup.delete_user_data(_plain(db_state), uid)
    assert await _count(db_state, EventFollow) == 0
