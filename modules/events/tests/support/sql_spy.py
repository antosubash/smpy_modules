"""Count the statements a block sends: for "no SQL before the arguments are checked" and "a fixed
number of statements"."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event as sa_event

__all__ = ["Spy"]


class Spy:
    def __init__(self, db_state: Any) -> None:
        self.engine = db_state.engine.sync_engine
        self.seen: list[str] = []

    def _on(self, _conn, _cursor, statement, *_rest):
        self.seen.append(statement)

    def __enter__(self):
        sa_event.listen(self.engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        sa_event.remove(self.engine, "before_cursor_execute", self._on)
