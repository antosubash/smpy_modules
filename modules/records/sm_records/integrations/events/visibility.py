"""Which record types a caller may read, whether or not they still have a date field, and what
that means for a source's settings: a mapping to a type the caller may not read is hidden from
them, whatever the reason (the type is gone, or it is not theirs), so neither is an oracle for
the other.

``view_settings`` and ``restore_settings`` are the optional hooks of the events ``Source``
protocol. A hidden mapping is shown as ``{"hidden": true, "token": "h<index>"}``: no type, field
or colour. On save the client sends the placeholder back and the server puts the stored mapping
in its place untouched, and it puts back one the client left out, so a manager can neither read,
change nor remove what they may not see (turning the whole source off still drops it).
"""

from __future__ import annotations

import re
from typing import Any

from sm_events.contracts.extensions import (
    RestoredSettings,
    SettingsContext,
    SettingsProblem,
    SettingsView,
    SourceSettingsError,
)
from sqlalchemy import select
from sqlmodel import col

from sm_records.contracts._dated_access import DatedCaller, may_read
from sm_records.core.tenancy import tenant_scope
from sm_records.integrations.events.settings import caller_of
from sm_records.models import RecordType
from sm_records.records.index._fields import declared_keys, indexed_map
from sm_records.schema.types import IndexKind

__all__ = ["restore_settings", "view_settings"]

UNAVAILABLE = "That record type does not exist, or you may not read it"
TOKEN = re.compile(r"^h(\d{1,3})$")
_DATE_KINDS = {IndexKind.DATE, IndexKind.DATETIME}


async def readable_types(
    db: Any, tenant_id: str, caller: DatedCaller
) -> dict[str, tuple[set[str], dict[str, IndexKind]]]:
    """``{type key: (declared field keys, indexed date fields by key)}`` of the types ``caller``
    may read."""
    out: dict[str, tuple[set[str], dict[str, IndexKind]]] = {}
    with tenant_scope(tenant_id):
        stmt = select(RecordType).where(col(RecordType.tenant_id) == tenant_id)
        for rtype in (await db.execute(stmt)).scalars().all():
            if not may_read(rtype, caller):
                continue
            fields = list(rtype.fields or [])
            dated = {k: f.kind for k, f in indexed_map(fields).items() if f.kind in _DATE_KINDS}
            out[rtype.key] = (declared_keys(fields), dated)
    return out


def _mappings(settings: dict[str, Any]) -> list[Any]:
    raw = settings.get("mappings")
    return raw if isinstance(raw, list) else []


def _hidden(mapping: Any, readable: dict[str, Any]) -> bool:
    key = mapping.get("type_key") if isinstance(mapping, dict) else None
    return not isinstance(key, str) or key not in readable


def _problem(index: int, name: str, code: str, message: str) -> SettingsProblem:
    return SettingsProblem(("mappings", index, name), code, message)


def _problems(index: int, mapping: dict[str, Any], types: dict[str, Any]) -> list[SettingsProblem]:
    declared, dated = types[mapping["type_key"]]
    found: list[SettingsProblem] = []
    for name in ("field", "end_field"):
        value = mapping.get(name)
        if not isinstance(value, str):
            continue
        if value not in declared:
            found.append(_problem(index, name, "field_missing", "This field no longer exists"))
        elif value not in dated:
            found.append(
                _problem(index, name, "field_not_date", "This field is no longer an indexed date")
            )
    return found


async def view_settings(sctx: SettingsContext, settings: dict[str, Any]) -> SettingsView:
    caller = caller_of(sctx.viewer)
    assert caller is not None
    types = await readable_types(sctx.db, sctx.tenant_id, caller)
    shown: list[Any] = []
    problems: list[SettingsProblem] = []
    for index, mapping in enumerate(_mappings(settings)):
        if _hidden(mapping, types):
            shown.append({"hidden": True, "token": f"h{index}"})
            continue
        shown.append(mapping)
        problems.extend(_problems(index, mapping, types))
    return SettingsView({**settings, "mappings": shown}, tuple(problems))


async def restore_settings(
    sctx: SettingsContext, submitted: dict[str, Any], stored: dict[str, Any]
) -> RestoredSettings:
    caller = caller_of(sctx.viewer)
    assert caller is not None
    old = _mappings(stored)
    types = await readable_types(sctx.db, sctx.tenant_id, caller)
    hidden_at = [i for i, m in enumerate(old) if _hidden(m, types)]
    result: list[Any] = []
    used: set[int] = set()
    for position, mapping in enumerate(_mappings(submitted)):
        if not (isinstance(mapping, dict) and mapping.get("hidden") is True):
            result.append(mapping)
            continue
        match = TOKEN.match(str(mapping.get("token", "")))
        index = int(match.group(1)) if match else -1
        if index not in hidden_at or index in used or set(mapping) - {"hidden", "token"}:
            # forged, repeated or not hidden from this caller: the answer for an unknown type
            raise SourceSettingsError(
                ("mappings", position, "type_key"), UNAVAILABLE, "type_unavailable"
            )
        used.add(index)
        result.append(old[index])
    preserved = [("mappings", i) for i, m in enumerate(result) if _is_stored(m, old, hidden_at)]
    for index in hidden_at:  # one the client left out stays: it cannot see it to remove it
        if index not in used:
            result.append(old[index])
            preserved.append(("mappings", len(result) - 1))
    return RestoredSettings({**submitted, "mappings": result}, tuple(preserved))


def _is_stored(mapping: Any, old: list[Any], hidden_at: list[int]) -> bool:
    return any(mapping is old[i] for i in hidden_at)
