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
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import event

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


async def run_isolated[T](db: Any, timeout: float, call: Callable[[], Awaitable[T]]) -> T:
    """``await call()`` in a savepoint on ``db`` with a ``timeout`` in seconds.

    Raises whatever ``call`` raises, ``TimeoutError``, :class:`PluginWrote` or, when the
    rollback itself fails, :class:`SessionBroken`."""
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
            result = await call()
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
