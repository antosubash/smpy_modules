"""Write-ahead object intents (plan decision 4).

Before an object is written, its key is recorded in a session that commits on
its own, so a crash or a rolled-back caller leaves a row the janitor can reap.
The caller removes the intents in the *same* transaction that commits the row
referencing the objects (:func:`clear_intents`).

**Which session factory.** The intent session must be independent of the
caller's, so it needs a factory, not a session:

* web process: ``on_startup`` calls :func:`use_session_factory` once with
  ``app.state.sm.db.session_factory``; handlers then just ``object_intent(keys)``;
* worker (no app): Task 10's worker runtime builds its engine and session
  factory, then either calls :func:`use_session_factory` at process start or
  passes ``session_factory=`` per call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from simple_module_db.independent import independent_session
from sqlalchemy import delete

from sm_images.models.object_intent import ObjectIntent

_default_factory: Any = None


def use_session_factory(factory: Any) -> None:
    """Set the process-wide default factory for :func:`object_intent`."""
    global _default_factory
    _default_factory = factory


def current_factory() -> Any:
    """The process-wide session factory (also what contracts open sessions from)."""
    if _default_factory is None:
        raise RuntimeError("no session factory: call use_session_factory() at startup")
    return _default_factory


@asynccontextmanager
async def object_intent(keys: Iterable[str], *, session_factory: Any = None) -> AsyncIterator[None]:
    """Record ``keys`` durably, then run the write inside the block."""
    factory = session_factory or _default_factory
    if factory is None:
        raise RuntimeError(
            "no session factory for object intents: call use_session_factory() at startup "
            "or pass session_factory="
        )
    unique = list(dict.fromkeys(keys))
    if unique:
        async with independent_session(factory) as session:
            for key in unique:
                await session.merge(ObjectIntent(key=key))
    yield


async def clear_intents(db: Any, keys: Iterable[str]) -> None:
    """Delete the intents in the caller's session (commit with the referencing row)."""
    unique = list(dict.fromkeys(keys))
    if unique:
        await db.execute(delete(ObjectIntent).where(ObjectIntent.key.in_(unique)))
