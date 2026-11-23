"""What the token resolver's tests share: a world with one link, and ways to change it."""

from __future__ import annotations

from sharing.models import ResourceShare
from sm_events.feeds.tokens import service
from sm_events.feeds.tokens.resolve import lookup, resolve
from sm_events.models import Calendar, FeedToken
from sqlalchemy import delete, event, select

from tests.support.access import principal
from tests.support.tokens import NOW, fake_request

V = "events.view"


class Statements:
    """Counts the statements an engine runs, for 'exactly one' and 'the same number'."""

    def __init__(self, state) -> None:
        self.count = 0
        self._engine = state.engine.sync_engine
        event.listen(self._engine, "after_cursor_execute", self._hit)

    def _hit(self, *_args) -> None:
        self.count += 1

    def reset(self) -> int:
        seen, self.count = self.count, 0
        return seen

    def close(self) -> None:
        event.remove(self._engine, "after_cursor_execute", self._hit)


async def mint(app, state, calendar, user, perms=(V,)):
    async with state.session_factory() as db:
        got = await service.create_token(
            db,
            fake_request(app),
            principal(user, *perms),
            calendar.id,
            label="Phone",
            locale="en",
            now=NOW,
        )
        await db.commit()
        return got


async def resolve_for(app, state, secret, *, host_tenant=None):
    async with state.session_factory() as db:
        row = await lookup(db, secret)
        return await resolve(app, db, fake_request(app), row, host_tenant=host_tenant)


async def drop_share(state, cals, user="sv"):
    async with state.session_factory() as db:
        await db.execute(
            delete(ResourceShare.__table__).where(  # type: ignore[arg-type]
                ResourceShare.__table__.c.subject_id == user,
                ResourceShare.__table__.c.tenant_id == "default",
            )
        )
        await db.commit()


async def set_trash(state, calendar, trashed: bool):
    async with state.session_factory() as db:
        cal = (
            await db.execute(
                select(Calendar)
                .where(Calendar.id == calendar.id)
                .execution_options(include_deleted=True)
            )
        ).scalar_one()
        cal.is_deleted = trashed
        await db.commit()


async def last_used(state, token_id):
    async with state.session_factory() as db:
        db.sync_session.expire_all()
        return (
            await db.execute(select(FeedToken.last_used_at).where(FeedToken.id == token_id))
        ).scalar_one()
