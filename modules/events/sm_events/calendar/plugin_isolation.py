"""Run one piece of plugin code against the request's session without letting it hurt.

A plugin reads in the request's snapshot and tenant, so it gets the caller's session,
but only inside a SAVEPOINT that is **always** rolled back (a read needs no release):
a failing statement then rolls back only that savepoint, and on Postgres the request's
transaction is not aborted. The call has a wall-clock timeout. ``commit``, ``rollback``
and ``close`` are blocked on the session for the duration, and afterwards the session's
root transaction must be the same object and ``new``/``dirty``/``deleted`` empty: a
plugin that wrote anyway gets :class:`PluginWrote`, its pending changes are dropped and
the savepoint is rolled back. A flush of the plugin's own pending rows counts too (they
are then in the savepoint, which is discarded, but it is a bug worth reporting).

This guards against plugin *bugs*, not malice: a plugin is code the operator installed.
A plugin that swallows ``CancelledError`` or blocks the loop with synchronous work
cannot be pre-empted.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.pool import SingletonThreadPool, StaticPool

__all__ = ["PluginWrote", "SessionBroken", "run_isolated"]

_BLOCKED = ("commit", "rollback", "close")


class PluginWrote(Exception):  # noqa: N818 - a verdict, not an error type
    """The plugin wrote, committed or tried to end the transaction."""


class SessionBroken(Exception):  # noqa: N818 - the session cannot be trusted any more
    """The savepoint could not be rolled back: nothing further may run on this session."""


def _blocked(name: str) -> Callable[..., Awaitable[None]]:
    async def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise PluginWrote(f"a plugin may not call session.{name}()")

    return refuse


def _block(db: Any) -> list[str]:
    """Shadow ``commit``/``rollback``/``close`` on this session instance. A session class
    without an instance ``__dict__`` cannot be shadowed; the checks afterwards still hold."""
    done: list[str] = []
    for name in _BLOCKED:
        try:
            setattr(db, name, _blocked(name))
        except AttributeError:
            continue
        done.append(name)
    return done


def _discard_pending(db: Any) -> None:
    for obj in list(db.new):
        db.expunge(obj)
    for obj in [*db.dirty, *db.deleted]:
        db.expire(obj)


async def _run_shared[T](db: Any, timeout: float, call: Callable[[Any], Awaitable[T]]) -> T:
    """The fallback where no second connection can be had: ``await call(db)`` in a savepoint
    on the caller's session. A timeout that leaves the session needing a rollback (it fired
    inside a statement) is :class:`SessionBroken`: the caller must stop using it."""
    await db.flush()
    root = db.sync_session.get_transaction()
    blocked = _block(db)
    flushed: list[bool] = []

    def saw_flush(session: Any, *_args: Any) -> None:
        if session.new or session.dirty or session.deleted:
            flushed.append(True)

    event.listen(db.sync_session, "before_flush", saw_flush)
    savepoint = None
    try:
        async with asyncio.timeout(timeout) as budget:
            savepoint = await db.begin_nested()
            result = await call(db)
        if budget.expired():  # it swallowed the cancellation and finished late
            raise TimeoutError
        if flushed or db.sync_session.get_transaction() is not root:
            raise PluginWrote("the plugin changed the session")
        if db.new or db.dirty or db.deleted:
            raise PluginWrote("the plugin changed the session")
        return result
    finally:
        event.remove(db.sync_session, "before_flush", saw_flush)
        for name in blocked:
            vars(db).pop(name, None)
        try:
            _discard_pending(db)
            if savepoint is not None and savepoint.is_active:
                await savepoint.rollback()
        except Exception as exc:
            raise SessionBroken(type(exc).__name__) from exc
        try:  # cancelled inside a statement, SQLAlchemy invalidates the connection: is it usable?
            await db.execute(text("SELECT 1"))
        except Exception as exc:
            raise SessionBroken(type(exc).__name__) from exc


_TASKS: set[asyncio.Task[None]] = set()


def _own_session(db: Any) -> Any | None:
    """A new session of the caller's class on its own connection, or ``None`` when the engine
    shares one connection between sessions (the in-memory test engine), where a second session
    would roll back the first's transaction. The tenancy listeners are on the session class and
    the tenant is a context variable, so the new session is bound exactly as the caller's is."""
    bind = getattr(db, "bind", None)
    pool = getattr(getattr(bind, "sync_engine", bind), "pool", None)
    if pool is None or isinstance(pool, StaticPool | SingletonThreadPool):
        return None
    return type(db)(bind=bind, sync_session_class=type(db.sync_session), expire_on_commit=False)


async def _discard(session: Any) -> None:
    """Roll back and close; a connection that cannot be closed cleanly is invalidated, never
    returned dirty to the pool."""
    try:
        await type(session).rollback(session)  # the class's, not the shadowed instance attribute
        await type(session).close(session)
    except Exception:
        with contextlib.suppress(Exception):
            await session.invalidate()


async def _statement_timeout(session: Any, seconds: float) -> None:
    """Have Postgres stop a statement at the call's budget (``SET LOCAL``: this transaction)."""
    if session.bind.dialect.name == "postgresql":
        await session.execute(text(f"SET LOCAL statement_timeout = {max(1, int(seconds * 1000))}"))


async def _run_own[T](session: Any, timeout: float, call: Callable[[Any], Awaitable[T]]) -> T:
    blocked = _block(session)
    flushed: list[bool] = []

    def saw_flush(sess: Any, *_args: Any) -> None:
        if sess.new or sess.dirty or sess.deleted:
            flushed.append(True)

    event.listen(session.sync_session, "before_flush", saw_flush)
    try:
        async with asyncio.timeout(timeout) as budget:
            await _statement_timeout(session, timeout)
            result = await call(session)
        if budget.expired():  # it swallowed the cancellation and finished late
            raise TimeoutError
        if flushed or session.new or session.dirty or session.deleted:
            raise PluginWrote("the plugin changed the session")
        return result
    finally:
        for name in blocked:
            vars(session).pop(name, None)
        # Shielded: a cancelled request must still give the connection back.
        closing = asyncio.ensure_future(_discard(session))
        _TASKS.add(closing)
        closing.add_done_callback(_TASKS.discard)
        await asyncio.shield(closing)


async def run_isolated[T](db: Any, timeout: float, call: Callable[[Any], Awaitable[T]]) -> T:
    """``await call(session)`` with a ``timeout`` in seconds, on a session of its own (its own
    connection, rolled back and closed afterwards, shielded from cancellation) so that a
    timeout, a cancelled statement or bad SQL can only break the plugin's connection. Where
    the engine cannot give a second connection, on a savepoint of ``db`` instead.

    Raises whatever ``call`` raises, ``TimeoutError``, :class:`PluginWrote` or, in the
    fallback, :class:`SessionBroken` when ``db`` can no longer be used."""
    if (own := _own_session(db)) is not None:
        return await _run_own(own, timeout, call)
    return await _run_shared(db, timeout, call)
