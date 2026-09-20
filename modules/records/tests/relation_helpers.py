"""Building a two-type relation graph over HTTP, for the §9 tests.

Shared by ``test_expand.py``, ``test_expand_batching.py`` and the referrers
suite so each stays under the 300-line cap with one copy of the setup. Types
and records are created through the real API rather than seeded: a relation is
only half stored in the payload — the other half is the ``records_index_ref``
row the writer produces — and a seeded record has none.
"""

from __future__ import annotations

from sm_records.models import Record
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from tests.app_harness import ADMIN, roles

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
"""Headers that make an Inertia view answer with its props as JSON."""


def field(key: str, type_: str, **options) -> dict:
    """One raw field definition. The label is derived from the key so a test
    asserting on ``field_label`` is asserting on the *referring type's* stored
    definition rather than on a string it passed in alongside it."""
    return {
        "key": key,
        "type": type_,
        "label": key.replace("_", " ").title(),
        "options": options,
    }


async def make_type(client, key: str, fields: list[dict], **cols) -> dict:
    resp = await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": fields, "display_field": "name", **cols},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_record(client, key: str, data: dict, *, actor: str = ADMIN) -> dict:
    resp = await client.post(
        f"/api/records/types/{key}/records", json={"data": data}, headers=roles(actor)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def library(client, *, author_roles: list[str] | None = None, many: bool = False):
    """An ``author`` type and a ``book`` type pointing at it.

    ``on_delete`` stays at its ``restrict`` default: these tests trash and
    purge the *target* behind the module's back precisely because the delete
    path would otherwise refuse (``restrict``) or rewrite the referrer
    (``set_null``/``cascade``) — and what is under test is how a reference
    that survived reads, not how a delete behaves.
    """
    await make_type(
        client,
        "author",
        [field("name", "text")],
        allowed_roles=author_roles or [],
    )
    await make_type(
        client,
        "book",
        [
            field("name", "text"),
            field("author", "relation", target_type="author", many=many),
        ],
    )


async def trash(db_state, uuid: str) -> None:
    """Soft-delete one record without going through the delete path."""
    async with db_state.session_factory() as session:
        row = (await session.execute(select(Record).where(Record.uuid == uuid))).scalars().first()
        row.is_deleted = True
        session.add(row)
        await session.commit()


async def purge(db_state, uuid: str) -> None:
    """Really remove the row, leaving the referrer's stored reference behind."""
    async with db_state.session_factory() as session:
        await session.execute(sa_delete(Record).where(Record.uuid == uuid))
        await session.commit()
