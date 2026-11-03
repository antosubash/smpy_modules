"""Existing schema performance setup and timing helpers."""

from __future__ import annotations

from sm_records.records.services import schema_change

from tests.perf._bench import Timing
from tests.perf.conftest import load_type


def _fields(rtype) -> list[dict]:
    return [dict(raw) for raw in (rtype.fields or [])]


def _one(timing_ms: float) -> Timing:
    """A single-shot measurement as a :class:`Timing` — these operations run
    for seconds and are not repeated twenty times."""
    return Timing(samples=[timing_ms])


def _settings():
    from sm_records.core.settings import RecordsSettings

    return RecordsSettings()


async def _set_indexed(db_state, settings, key: str, value: bool) -> int:
    """Set ``store.<key>``'s ``indexed`` flag and return the type id.

    A no-op when the flag already has that value — ``apply`` would refuse a
    change that changes nothing, and the caller only wants the state.
    """
    async with db_state.session_factory() as session:
        rtype = await load_type(session, "store")
        raw = _fields(rtype)
        changed = False
        for field in raw:
            if field["key"] == key and bool(field.get("indexed", False)) != value:
                field["indexed"] = value
                changed = True
        if changed:
            await schema_change.apply(
                session,
                rtype,
                fields_raw=raw,
                expected_version=rtype.version,
                settings=settings,
            )
            await session.commit()
        return rtype.id
