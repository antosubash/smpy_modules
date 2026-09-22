"""The recorder every event test subscribes to, and the fixtures around it.

Split out of ``tests/test_events.py`` for the 300-line cap. It holds the one
piece of machinery both files need: a subscriber that keeps every event in
publication order *and* records, per event, whether the write behind it was
already visible from another session — which is the after-commit assertion,
not a paraphrase of one.
"""

from __future__ import annotations

import json
from typing import Any

from sm_records.contracts.events import (
    RecordCreated,
    RecordPurged,
    RecordRestored,
    RecordTrashed,
    RecordTypeChanged,
    RecordTypeDeleted,
    RecordUpdated,
)
from sm_records.models import Record, RecordType
from sqlalchemy import select

from tests.app_harness import ADMIN, roles

TYPES = "/api/records/types"
API = f"{TYPES}/note/records"

EVENT_TYPES = (
    RecordCreated,
    RecordUpdated,
    RecordTrashed,
    RecordRestored,
    RecordPurged,
    RecordTypeChanged,
    RecordTypeDeleted,
)


class Recorder:
    """Every event, in publication order, each tagged with whether the write
    behind it was already committed when it arrived."""

    def __init__(self, db_state: Any) -> None:
        self._db_state = db_state
        self.seen: list[Any] = []
        self.committed: list[bool] = []

    def subscribe(self, bus: Any) -> None:
        for event_type in EVENT_TYPES:
            bus.subscribe(event_type, self._handle)

    async def _handle(self, event: Any) -> None:
        self.seen.append(event)
        self.committed.append(await self._visible(event))

    async def _visible(self, event: Any) -> bool:
        """Is what the event describes already readable from another session?

        For a record event, the record (or its absence, for a purge). For a
        type event, the type row. A handler that ran inside the request's
        transaction would see the *old* state through a second connection, so
        this is the after-commit assertion rather than a paraphrase of one.
        """
        uuid = getattr(event, "uuid", None)
        async with self._db_state.session_factory() as session:
            if uuid is None:
                rows = (
                    (
                        await session.execute(
                            select(RecordType).where(RecordType.key == event.type_key)
                        )
                    )
                    .scalars()
                    .all()
                )
                return bool(rows) if isinstance(event, RecordTypeChanged) else not rows
            stmt = select(Record).where(Record.uuid == uuid).execution_options(include_deleted=True)
            found = (await session.execute(stmt)).scalars().first()
            if isinstance(event, RecordPurged):
                return found is None
            if isinstance(event, RecordTrashed):
                return found is not None and found.is_deleted is True
            if isinstance(event, RecordRestored):
                return found is not None and found.is_deleted is False
            if isinstance(event, RecordUpdated):
                return found is not None and found.version == event.version
            return found is not None

    def only(self, event_type: type) -> list[Any]:
        return [event for event in self.seen if isinstance(event, event_type)]


def _document(rows: list[dict]) -> str:
    """The JSON import shape: an object with a ``records`` list, each row an
    envelope around ``data``."""
    return json.dumps({"records": rows})


def _field(key: str, type_: str, **kw: Any) -> dict:
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "required": kw.pop("required", False),
        "unique": False,
        "indexed": kw.pop("indexed", True),
        "default": None,
        "help": None,
        "constraints": {},
        "options": kw,
    }


def recorder(client) -> Recorder:
    """Subscribe a fresh :class:`Recorder` to this app's bus.

    A function rather than a fixture, and the fixtures live in each test file:
    importing a fixture by name into two modules is what makes ruff read the
    test signature that uses it as a redefinition.
    """
    seen = Recorder(client.db_state)
    seen.subscribe(client.app.state.sm.event_bus)
    return seen


async def make_note(client) -> dict:
    resp = await client.post(
        TYPES,
        json={
            "key": "note",
            "label": "Note",
            "fields": [_field("title", "text")],
            "display_field": "title",
            "translatable": True,
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create(client, title: str = "One", **body: Any) -> dict:
    resp = await client.post(API, json={"data": {"title": title}, **body}, headers=roles(ADMIN))
    assert resp.status_code == 201, resp.text
    return resp.json()
