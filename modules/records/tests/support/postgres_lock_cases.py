"""Shared setup for test_postgres_lock."""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType
from sm_records.records.services.errors import Conflict, RecordsError
from sm_records.records.services.records import create_record
from sm_records.records.services.type_writes._type_update import update_type
from sm_records.schema.types import FieldType
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

WRITERS = 20


SETTINGS = RecordsSettings()


def _field(key: str, **overrides: Any) -> dict[str, Any]:
    definition = {"key": key, "type": "text", "label": key.title(), "indexed": True}
    definition.update(overrides)
    return definition


async def _seed_type(state: Any, key: str, fields: list[dict], **cols: Any) -> int:
    async with state.session_factory() as session:
        rtype = RecordType(
            key=key,
            label=key.title(),
            label_plural=f"{key.title()}s",
            fields=fields,
            **cols,
        )
        session.add(rtype)
        await session.commit()
        return int(rtype.id)


async def _one_create(state: Any, type_id: int, data: dict[str, Any]) -> str:
    """One writer: its own session, its own transaction, its own outcome.

    The outcome is a short string rather than an exception so ``gather`` need
    not run with ``return_exceptions`` and hide an unexpected failure among
    the expected ones. ``IntegrityError`` is caught separately because "the
    database refused it and nothing turned that into a 409" is the exact
    regression :func:`sm_records.records.services.claims._claims.flush_write` prevents, and a
    test lumping it in with ``Conflict`` could not see it.
    """
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        try:
            await create_record(session, rtype, data=dict(data), settings=SETTINGS)
            await session.commit()
        except Conflict:
            await session.rollback()
            return "conflict"
        except IntegrityError:
            await session.rollback()
            return "integrity-error"
        except RecordsError as exc:
            await session.rollback()
            return f"records-error:{type(exc).__name__}"
        return "created"


async def _race(state: Any, type_id: int, data: dict[str, Any]) -> Counter:
    outcomes = await asyncio.wait_for(
        asyncio.gather(*(_one_create(state, type_id, data) for _ in range(WRITERS))),
        timeout=60,
    )
    return Counter(outcomes)


async def _stored(state: Any, type_id: int) -> int:
    async with state.session_factory() as session:
        total = await session.execute(
            select(func.count(Record.id))
            .where(Record.type_id == type_id)
            .execution_options(include_deleted=True)
        )
        return int(total.scalar_one())


async def _edit_schema(state: Any, type_id: int) -> str:
    """Add a field to the type while records are landing against it."""
    async with state.session_factory() as session:
        rtype = await session.get(RecordType, type_id)
        try:
            await update_type(
                session,
                rtype,
                expected_version=rtype.version,
                settings=SETTINGS,
                fields_raw=[
                    _field("name"),
                    _field("email", unique=True),
                    _field("nickname", type=FieldType.TEXT.value),
                ],
            )
            await session.commit()
        except (Conflict, IntegrityError):
            await session.rollback()
            return "conflict"
        except RecordsError as exc:
            await session.rollback()
            return f"records-error:{type(exc).__name__}"
        return "edited"
