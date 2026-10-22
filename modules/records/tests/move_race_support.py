"""Shared by the move race suites (``test_collections_move_race*.py``).

A type of three records in the shared tables — two live, one trashed — and
the move that takes it to ``events``, both through the service layer on a
session the caller owns, so each side of a race is its own transaction.
"""

from __future__ import annotations

from typing import Any

from sm_records.models import RecordType, table_set
from sm_records.services._lifecycle import soft_delete_record
from sm_records.services._type_update import update_type
from sm_records.services.records import create_record
from sm_records.settings import RecordsSettings
from sqlalchemy import func, select

SETTINGS = RecordsSettings()
FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


async def seed(
    state: Any, key: str = "author", fields: list[dict] | None = None
) -> tuple[int, dict[str, str]]:
    """``(type id, {"live-0" | "live-1" | "binned": uuid})``, committed."""
    async with state.session_factory() as session:
        rtype = RecordType(
            key=key,
            label=key.title(),
            label_plural=f"{key.title()}s",
            fields=fields or FIELDS,
            display_field="name",
        )
        session.add(rtype)
        await session.flush()
        made = {
            name: await create_record(session, rtype, data={"name": name}, settings=SETTINGS)
            for name in ("live-0", "live-1", "binned")
        }
        await soft_delete_record(session, rtype, made["binned"], settings=SETTINGS)
        await session.commit()
        return int(rtype.id), {name: record.uuid for name, record in made.items()}


async def move(session: Any, type_id: int, target: str | None = "events") -> None:
    """Move the type, uncommitted — the caller decides when it lands."""
    rtype = await session.get(RecordType, type_id)
    await update_type(
        session, rtype, expected_version=rtype.version, settings=SETTINGS, collection=target
    )


async def count(
    state: Any, collection: str | None, type_id: int, *, trashed: bool | None = None
) -> int:
    """Rows of the type in ``collection``'s record table — all of them, or
    only the trash (``trashed=True``)."""
    record = table_set(collection).record
    stmt = select(func.count()).select_from(record).where(record.type_id == type_id)
    if trashed:
        stmt = stmt.where(record.is_deleted.is_(True))
    async with state.session_factory() as session:
        return int(await session.scalar(stmt.execution_options(include_deleted=True)) or 0)
