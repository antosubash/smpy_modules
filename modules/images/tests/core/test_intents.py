"""Object intents: written before the object, survive a caller's rollback."""

from __future__ import annotations

from sm_images.intents import clear_intents, object_intent, use_session_factory
from sm_images.models.object_intent import ObjectIntent
from sqlalchemy import select

KEYS = ["images/default/c/i/original.jpg", "images/default/c/i/display.1.jpg"]


async def _keys(db_state) -> set[str]:
    async with db_state.session_factory() as s:
        return set((await s.execute(select(ObjectIntent.key))).scalars())


async def test_intent_survives_rollback_and_clears_on_commit(images_app):
    _, db_state = images_app
    use_session_factory(db_state.session_factory)
    async with db_state.session_factory() as caller:
        async with object_intent(KEYS):
            assert await _keys(db_state) == set(KEYS)
        await caller.rollback()
    assert await _keys(db_state) == set(KEYS)  # reapable orphan

    async with db_state.session_factory() as caller:
        await clear_intents(caller, KEYS)
        await caller.commit()
    assert await _keys(db_state) == set()


async def test_explicit_factory_and_repeat_is_idempotent(images_app):
    _, db_state = images_app
    async with object_intent(KEYS[:1], session_factory=db_state.session_factory):
        pass
    async with object_intent(KEYS[:1], session_factory=db_state.session_factory):
        pass
    assert await _keys(db_state) == set(KEYS[:1])


async def test_caller_rollback_drops_its_row_but_keeps_the_intent(tmp_path):
    """The realistic order: the handler has already read, writes the intent, then
    inserts and flushes the referencing row, then fails and rolls back.

    On a file database (one connection per session, like a host) so the intent's
    commit cannot ride along with, or be undone by, the caller's transaction -
    the shared ``StaticPool`` connection would hide exactly that.
    """
    from sm_images.models import Collection

    from tests.support.pg import make_db_state

    db_state = await make_db_state(file=tmp_path / "intents.db")
    try:
        use_session_factory(db_state.session_factory)
        async with db_state.session_factory() as caller:
            await caller.execute(select(Collection.id))
            async with object_intent(KEYS):
                caller.add(Collection(slug="c", name="c", owner_id="u"))
                await caller.flush()
            await caller.rollback()
        async with db_state.session_factory() as s:
            assert (await s.execute(select(Collection.id))).all() == []
        assert await _keys(db_state) == set(KEYS)
    finally:
        await db_state.engine.dispose()
