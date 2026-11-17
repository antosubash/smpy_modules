"""The calendar list answers in a fixed number of statements, however long it is."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.support.access import grant
from tests.support.calendars import BASE, EDITOR, OWNER, SV, make

VISIBILITIES = ("private", "internal", "public")


async def _seed(client, count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        headers = OWNER if i % 2 == 0 else EDITOR
        made = await make(client, headers, name=f"Cal {i:03d}", visibility=VISIBILITIES[i % 3])
        if i % 3 == 0:
            await grant(client, made["id"], "sv", "view" if i % 2 else "edit")


async def _statements(client) -> tuple[int, int]:
    seen: list[str] = []

    def spy(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", spy)
    try:
        got = await client.get(BASE, headers=SV)
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert got.status_code == 200, got.text
    return len(seen), len(got.json())


async def test_list_statement_count_does_not_grow_with_calendars(client):
    await _seed(client, 5)
    few, few_rows = await _statements(client)
    await _seed(client, 15, start=5)
    many, many_rows = await _statements(client)
    assert many_rows > few_rows > 0
    assert many == few, (few, many)
